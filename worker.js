// The Slow Swing — Worker
// -----------------------------------------------------------------------------
//   POST /api/signup   {email, plan}  -> {ok:true}          start a 30-day trial
//   POST /api/login    {email}        -> {ok:true}          email a magic link
//   GET  /api/auth?token=..           -> 302 + session cookie
//   GET  /api/me                      -> {authed, email, status, daysLeft}
//   GET  /api/board                   -> board JSON  (401/403 if not entitled)
//   GET  /api/logout                  -> 302, clears session
//   POST /api/checkout {plan}         -> {url}   Stripe Checkout (trial -> paid)
//   POST /api/portal                  -> {url}   Stripe billing portal (manage/cancel)
//   POST /api/stripe-webhook          -> 200     Stripe -> KV status sync
//   *                                 -> static assets (env.ASSETS)
//
// Bindings:
//   STORE            KV  (subscribers, board:current, login nonces)
//   RESEND_API_KEY   secret
//   SESSION_SECRET   secret   <- NEW. wrangler secret put SESSION_SECRET
//   STRIPE_SECRET_KEY       secret   wrangler secret put STRIPE_SECRET_KEY
//   STRIPE_WEBHOOK_SECRET   secret   wrangler secret put STRIPE_WEBHOOK_SECRET
//   EMAIL_FROM / NOTIFY_EMAIL / APP_URL           vars
//   STRIPE_PRICE_MONTHLY / _ANNUAL / _FOUNDERS    vars
//
// NOTE ON EXPIRY: there is deliberately NO cron. Entitlement is evaluated from
// trial_end on every request (see entitlement()). A trial expires the moment the
// clock passes it, with nothing scheduled to go wrong or drift.
// -----------------------------------------------------------------------------

const TRIAL_DAYS = 30;
const enc = new TextEncoder();
const dec = new TextDecoder();

// ---------- http ----------
const json = (d, s = 200, h = {}) =>
  new Response(JSON.stringify(d), {
    status: s,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...h },
  });
const redirect = (loc, h = {}) => new Response(null, { status: 302, headers: { location: loc, ...h } });

const normEmail = (e) => String(e || "").trim().toLowerCase();
const validEmail = (e) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e) && e.length <= 254;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const PLAN_LABEL = { monthly: "Monthly", annual: "Annual", founders: "Founders" };

function fmtET(d) {
  try { return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", dateStyle: "medium", timeStyle: "short" }).format(d) + " ET"; }
  catch { return d.toISOString(); }
}
function fmtDate(d) {
  try { return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", dateStyle: "medium" }).format(d); }
  catch { return d.toISOString().slice(0, 10); }
}

// ---------- base64url + HMAC tokens ----------
function b64url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64urlBytes(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = atob(s), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
async function hmacKey(secret) {
  return crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}
async function signToken(payload, secret) {
  const body = b64url(enc.encode(JSON.stringify(payload)));
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(secret), enc.encode(body));
  return `${body}.${b64url(sig)}`;
}
async function verifyToken(token, secret) {
  if (!token || token.indexOf(".") < 0) return null;
  const [body, sig] = token.split(".");
  let ok = false;
  try { ok = await crypto.subtle.verify("HMAC", await hmacKey(secret), b64urlBytes(sig), enc.encode(body)); }
  catch { return null; }
  if (!ok) return null;
  try {
    const p = JSON.parse(dec.decode(b64urlBytes(body)));
    if (p.exp && Date.now() > p.exp) return null;
    return p;
  } catch { return null; }
}

// ---------- cookies ----------
function cookies(request) {
  const out = {};
  (request.headers.get("cookie") || "").split(";").forEach((p) => {
    const i = p.indexOf("=");
    if (i > -1) out[p.slice(0, i).trim()] = decodeURIComponent(p.slice(i + 1).trim());
  });
  return out;
}
const setSession = (t) => `tss=${encodeURIComponent(t)}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=${60 * 60 * 24 * 30}`;
const clearSession = () => `tss=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0`;

// ---------- subscriber store ----------
const subKey = (e) => `sub:${normEmail(e)}`;
async function getSub(env, email) {
  const raw = await env.STORE.get(subKey(email));
  return raw ? JSON.parse(raw) : null;
}
async function putSub(env, email, rec) {
  await env.STORE.put(subKey(email), JSON.stringify(rec));
}

// Single source of truth for "may this person see the board?"
// Evaluated live from the record — no cron, nothing to fall out of sync.
function entitlement(sub) {
  if (!sub) return { ok: false, reason: "no_account", status: "none", daysLeft: 0 };
  const status = sub.status || "none";

  // A paid subscription is the strongest claim.
  if (status === "active" || status === "past_due") {
    return { ok: true, reason: "", status, daysLeft: null };
  }

  // Otherwise fall back to the trial window. This is checked even when the stored
  // status says "canceled": if someone subscribed and cancelled inside their first
  // 30 days, they keep what they were already given. Never claw back the trial.
  const end = Date.parse(sub.trial_end || "");
  if (isFinite(end) && end - Date.now() > 0) {
    return { ok: true, reason: "", status: "trialing",
             daysLeft: Math.max(1, Math.ceil((end - Date.now()) / 86400000)) };
  }

  if (status === "trialing") {
    return isFinite(end)
      ? { ok: false, reason: "trial_expired", status: "expired", daysLeft: 0 }
      : { ok: false, reason: "bad_record", status: "trialing", daysLeft: 0 };
  }
  if (status === "canceled") return { ok: false, reason: "canceled", status, daysLeft: 0 };
  return { ok: false, reason: status === "expired" ? "trial_expired" : "not_entitled", status, daysLeft: 0 };
}

// ---------- Stripe (REST, form-encoded — no SDK, keeps the worker small) ----------
function toForm(obj, prefix = "") {
  const parts = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === null) continue;
    const key = prefix ? `${prefix}[${k}]` : k;
    if (typeof v === "object") parts.push(toForm(v, key));
    else parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(v)}`);
  }
  return parts.join("&");
}
async function stripeApi(env, path, method = "GET", params = null) {
  const opts = { method, headers: { authorization: `Bearer ${env.STRIPE_SECRET_KEY}` } };
  if (params) {
    opts.headers["content-type"] = "application/x-www-form-urlencoded";
    opts.body = toForm(params);
  }
  const r = await fetch(`https://api.stripe.com/v1/${path}`, opts);
  return r.json();
}
function hex(buf) { return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join(""); }
function safeEq(a, b) {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}
async function verifyStripeSig(raw, header, secret, toleranceSec = 300) {
  if (!header || !secret) return false;
  const f = {};
  header.split(",").forEach((p) => {
    const i = p.indexOf("=");
    if (i > -1) { const k = p.slice(0, i).trim(); if (k === "t" || k === "v1") f[k] = f[k] || p.slice(i + 1).trim(); }
  });
  if (!f.t || !f.v1) return false;
  if (Math.abs(Date.now() / 1000 - Number(f.t)) > toleranceSec) return false;
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(secret), enc.encode(`${f.t}.${raw}`));
  return safeEq(hex(sig), f.v1);
}
// Stripe subscription status -> our stored status
function mapStripeStatus(s) {
  if (s === "active") return "active";
  if (s === "past_due") return "past_due";
  if (s === "trialing") return "active";           // we don't use Stripe trials; treat as paid
  if (s === "canceled" || s === "unpaid" || s === "incomplete_expired") return "canceled";
  return "incomplete";
}

// ---------- email ----------
async function sendEmail(env, { to, subject, html, text }) {
  if (!env.RESEND_API_KEY) return false;
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${env.RESEND_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify({
      from: env.EMAIL_FROM || "The Slow Swing <hello@send.theslowswing.com>",
      to: [to], reply_to: "support@theslowswing.com", subject, html, text,
    }),
  });
  // Log every non-2xx so `wrangler tail` shows WHY a send failed. Before this
  // a rejected send was indistinguishable from a delivered one.
  if (!r.ok) {
    let why = ""; try { why = (await r.text()).slice(0, 300); } catch (e) {}
    console.log(`resend ${r.status} to=${to} subject="${subject}" ${why}`);
  } else {
    console.log(`resend ok to=${to} subject="${subject}"`);
  }
  return r.ok;
}

const SIGNOFF_HTML = `<p style="margin:0 0 24px">Keep swinging,<br><b>The Slow Swing Team</b></p>
    <p style="margin:0;color:#64748b;font-size:12px;line-height:1.5">The Slow Swing is educational research, not investment advice. We are not a broker-dealer or investment adviser, and we don't execute trades. All figures shown are paper-tracked and hypothetical — levels a price reached, not returns anyone earned. Do your own research.</p>`;
const wrap = (inner) =>
  `<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:520px;margin:0 auto;color:#0f172a;line-height:1.55">${inner}${SIGNOFF_HTML}</div>`;
const btn = (href, label) =>
  `<p style="margin:0 0 26px"><a href="${href}" style="background:#0f766e;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;display:inline-block;font-weight:600">${label}</a></p>`;

function welcomeEmail(env, trialEnd, link, code) {
  const ends = fmtDate(trialEnd);
  const html = wrap(`
    <h2 style="color:#0f766e;margin:0 0 14px;font-size:22px">Welcome to The Slow Swing.</h2>
    <p style="margin:0 0 18px">Thanks for signing up. You have <b>full access for the next 30 days</b> — no card, nothing to cancel. Your trial runs through <b>${esc(ends)}</b>.</p>
    ${btn(link, "Open tonight's board →")}
    ${codeBlock(code)}
    <p style="margin:0 0 16px"><b>What to expect.</b> The board refreshes every evening after the close. Each name carries a Swing Score, a quality badge and the market-context read, plus the reasoning behind why it qualified.</p>
    <p style="margin:0 0 16px"><b>One thing worth knowing up front.</b> These are swing setups measured in weeks, not days. Most names dip before they work — that's normal, and the Journal explains why. If you check the board hourly expecting instant moves, you'll be reading it wrong. Give it the month.</p>
    <p style="margin:0 0 22px">Questions at any point — just reply to this email.</p>`);
  const text = `Welcome to The Slow Swing.

Thanks for signing up. You have full access for the next 30 days - no card, nothing to cancel. Your trial runs through ${ends}.

Open tonight's board: ${link}
${codeText(code)}
The board refreshes every evening after the close. These are swing setups measured in weeks, not days - most names dip before they work. Give it the month.

Questions at any point - just reply to this email.

Keep swinging,
The Slow Swing Team`;
  return { subject: "Welcome to The Slow Swing — your 30 days start now", html, text };
}

function returningEmail(env, trialEnd, daysLeft, link, code) {
  const ends = fmtDate(trialEnd), live = daysLeft > 0;
  const lead = live
    ? `You're already signed up — nothing to redo. Your access runs through <b>${esc(ends)}</b>, which is <b>${daysLeft} day${daysLeft === 1 ? "" : "s"}</b> from now. Re-submitting the form didn't change anything or cost you any time.`
    : `You're already signed up with us — your 30-day trial ran through <b>${esc(ends)}</b> and has now ended. Re-submitting the form doesn't restart it.`;
  const tail = live ? btn(link, "Open tonight's board →") + codeBlock(code)
    : `<p style="margin:0 0 22px">We'll be in touch as soon as subscriptions open. If you'd like to say something about how the month went, just reply — we read everything.</p>`;
  const html = wrap(`
    <h2 style="color:#0f766e;margin:0 0 14px;font-size:22px">${live ? "You're already in." : "Your trial has ended"}</h2>
    <p style="margin:0 0 18px">${lead}</p>
    ${tail}
    <p style="margin:0 0 22px">Questions at any point — just reply to this email.</p>`);
  const text = live
    ? `You're already in.\n\nYour access runs through ${ends}, which is ${daysLeft} day${daysLeft === 1 ? "" : "s"} from now. Re-submitting the form didn't change anything.\n\nOpen tonight's board: ${link}\n\nKeep swinging,\nThe Slow Swing Team`
    : `Your trial has ended.\n\nYour 30-day trial ran through ${ends}. Re-submitting the form doesn't restart it.\n\nWe'll be in touch as soon as subscriptions open.\n\nKeep swinging,\nThe Slow Swing Team`;
  return { subject: live ? "You're already signed up — here's the board" : "Your Slow Swing trial has ended", html, text };
}

// The code block shared by every email that carries a sign-in. Two routes,
// stated plainly so nobody tries the wrong one on the wrong screen.
function codeBlock(code) {
  if (!code) return "";
  const pretty = `${code.slice(0, 3)} ${code.slice(3)}`;
  return `
    <div style="margin:0 0 18px;padding:16px 18px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc">
      <div style="font-size:13px;color:#475569;margin-bottom:8px"><b>On a different device?</b> Type this code into the box on the screen where you entered your email:</div>
      <div style="font-size:30px;font-weight:800;letter-spacing:.18em;color:#0f172a;font-variant-numeric:tabular-nums">${pretty}</div>
      <div style="font-size:12px;color:#64748b;margin-top:8px">The button above signs in the device you tap it on. The code signs in the device where you asked for it. Both expire in 15 minutes.</div>
    </div>`;
}
function codeText(code) {
  return code ? `\nOn a different device? Enter this code where you typed your email: ${code.slice(0,3)} ${code.slice(3)}\n(The link signs in the device you open it on; the code signs in the device where you asked for it. Both expire in 15 minutes.)\n` : "";
}

function loginEmail(link, code) {
  const html = wrap(`
    <h2 style="color:#0f766e;margin:0 0 14px;font-size:22px">Your sign-in link</h2>
    <p style="margin:0 0 18px">Tap below to open tonight's board. This link works once and expires in 15 minutes.</p>
    ${btn(link, "Sign in →")}
    ${codeBlock(code)}
    <p style="margin:0 0 22px;color:#64748b;font-size:13px">If you didn't ask for this, you can ignore it — nothing happens until the link or code is used.</p>`);
  return { subject: "Your sign-in link for The Slow Swing", html, text: `Your sign-in link for The Slow Swing\n\n${link}\n${codeText(code)}\nWorks once, expires in 15 minutes. If you didn't ask for this, ignore it.\n\nKeep swinging,\nThe Slow Swing Team` };
}

// Sent when someone tries to sign in with an address we don't know. Before
// this, the login form answered "if that address has an account, a link is on
// its way" and sent NOTHING — a silent dead end that nobody could tell apart
// from spam-foldering. Emailing the address itself reveals nothing to anyone
// but its owner, and turns the dead end into a signup.
function noAccountEmail(env) {
  const app = env.APP_URL || "https://theslowswing.com";
  const html = wrap(`
    <h2 style="color:#0f766e;margin:0 0 14px;font-size:22px">We don't have an account for this address.</h2>
    <p style="margin:0 0 18px">Someone — probably you — asked for a sign-in link at The Slow Swing using this email, but there's no account under it yet.</p>
    <p style="margin:0 0 18px"><b>If you meant a different address</b>, try signing in with that one. <b>If you're new</b>, the free trial is 30 days, no card, nothing to cancel:</p>
    ${btn(app + "/?signup=1#pricing", "Start your free trial →")}
    <p style="margin:0 0 22px;color:#64748b;font-size:13px">If this wasn't you, ignore it — nothing has happened.</p>`);
  return { subject: "No account yet for this email — here's how to start", html,
    text: `We don't have an account for this address at The Slow Swing.\n\nIf you meant a different email, sign in with that one. If you're new, the free trial is 30 days, no card: ${app}/?signup=1#pricing\n\nIf this wasn't you, ignore it.\n\nKeep swinging,\nThe Slow Swing Team` };
}

function subscribedEmail(env, info) {
  const app = env.APP_URL || "https://theslowswing.com";
  const amount = info.amount != null ? `$${(info.amount / 100).toFixed(2)}` : null;
  const every = info.interval === "year" ? "year" : "month";
  const line = amount ? `<b>${amount} per ${every}</b>` : "your subscription";
  const renews = info.periodEnd ? fmtDate(new Date(info.periodEnd * 1000)) : null;
  // A trial conversion charges nothing today. Saying "renews on" to someone who
  // hasn't paid reads like a charge they didn't authorise — say "first charge".
  const onTrial = !!info.trialing;
  const when = onTrial
    ? (renews ? `Your card is saved and <b>nothing has been charged</b>. Your free trial runs to <b>${esc(renews)}</b>, and the first payment of ${line} is taken that day.` : `Your card is saved and <b>nothing has been charged</b> — the first payment comes when your free trial ends.`)
    : `Your subscription is ${line}${renews ? `, and it renews on <b>${esc(renews)}</b>` : ""}.`;
  const html = wrap(`
    <h2 style="color:#0f766e;margin:0 0 14px;font-size:22px">${onTrial ? "You're all set." : "You're subscribed."}</h2>
    <p style="margin:0 0 18px">Thanks for backing The Slow Swing. ${when} Nothing else changes — the board is where it always was.</p>
    ${btn(app + "/#board", "Open tonight's board \u2192")}
    <p style="margin:0 0 16px"><b>Cancelling is two clicks, any time.</b> Sign in and use the <b>Manage billing</b> link in the top bar \u2014 it opens your billing page where you can cancel, change card, or download receipts. You keep access through the end of the period you've already paid for, and we never add a cancellation fee or bury the button.</p>
    <p style="margin:0 0 22px">If anything looks wrong on this charge, just reply to this email.</p>`);
  const text = `${onTrial ? "You're all set." : "You're subscribed."}

Thanks for backing The Slow Swing. ${onTrial
  ? `Your card is saved and nothing has been charged. Your free trial runs to ${renews || "its end date"}, and the first payment${amount ? " of " + amount : ""} is taken that day.`
  : `Your subscription is ${amount ? amount + " per " + every : "active"}${renews ? ", renewing on " + renews : ""}.`}

Open the board: ${app}/#board

Cancelling is two clicks, any time: sign in and use the "Manage billing" link in the top bar. You keep access through the end of the period you've paid for.

If anything looks wrong on this charge, just reply to this email.

Keep swinging,
The Slow Swing Team`;
  return { subject: onTrial ? "Your Slow Swing trial is confirmed \u2014 no charge yet" : "You're subscribed to The Slow Swing", html, text };
}

// Stripe API 2026-08-26 moved current_period_end onto the subscription ITEM.
// Read the item first and fall back to the old top-level field, so this keeps
// working whichever API version the webhook endpoint is pinned to.
function subPeriodEnd(sub) {
  try {
    const it = sub.items && sub.items.data && sub.items.data[0];
    if (it && it.current_period_end) return it.current_period_end;
  } catch (e) {}
  return sub.current_period_end || sub.cancel_at || null;
}

// "Is this subscription winding down, and when?" — asked in a version-proof way.
// The Billing Portal on recent API versions records a scheduled cancellation as
// `cancel_at` and leaves the older `cancel_at_period_end` flag FALSE, while the
// Stripe dashboard still sets the flag. Trusting either one alone means missing
// half the real cancellations, which is exactly how a customer cancels and hears
// nothing back. Return the end date if it's ending, otherwise null.
function subEndsAt(sub) {
  if (!sub) return null;
  if (sub.cancel_at) return sub.cancel_at;
  if (sub.cancel_at_period_end) return subPeriodEnd(sub);
  return null;
}

// Sent once per cancellation. A customer who cancels gets it in writing — what
// they cancelled, when access actually stops, and that no further charge is
// coming. Silence here is how "I thought I cancelled" disputes start.
function canceledEmail(env, info) {
  const app = env.APP_URL || "https://theslowswing.com";
  const ends = info.endsAt ? fmtDate(new Date(info.endsAt * 1000)) : null;
  const immediate = !!info.immediate;
  const stillHas = !immediate && ends;

  const html = wrap(`
    <h2 style="color:#0f766e;margin:0 0 14px;font-size:22px">Your subscription is cancelled.</h2>
    <p style="margin:0 0 18px">${stillHas
      ? `You won't be charged again. You keep full access to the board through <b>${esc(ends)}</b> — the end of the period you've already paid for.`
      : `You won't be charged again, and access has ended.`}</p>
    ${stillHas ? btn(app + "/#board", "Open tonight's board →") : btn(app + "/#pricing", "Come back any time →")}
    <p style="margin:0 0 16px">Nothing else is needed from you. If you change your mind${stillHas ? " before " + esc(ends) : ""}, sign in and use <b>Manage billing</b> to restart — same email, same account.</p>
    <p style="margin:0 0 22px">If you cancelled because something wasn't working, reply and tell me. I read every one.</p>`);

  const text = `Your subscription is cancelled.

${stillHas
  ? `You won't be charged again. You keep full access through ${ends} - the end of the period you've already paid for.`
  : `You won't be charged again, and access has ended.`}

${stillHas ? app + "/#board" : app + "/#pricing"}

If you change your mind, sign in and use "Manage billing" to restart - same email, same account.

If you cancelled because something wasn't working, reply and tell me. I read every one.

Keep swinging,
The Slow Swing Team`;

  return { subject: "Your Slow Swing subscription is cancelled", html, text };
}

// Sent 3 days before a trial converts. The email that prevents a surprise charge
// is the one that arrives BEFORE the money moves — a receipt afterwards only tells
// someone what already happened to their card, which is how disputes start.
function trialEndingEmail(env, info) {
  const app = env.APP_URL || "https://theslowswing.com";
  const when = info.endsAt ? fmtDate(new Date(info.endsAt * 1000)) : null;
  const amount = info.amount != null ? `$${(info.amount / 100).toFixed(2)}` : null;
  const every = info.interval === "year" ? "year" : "month";
  const charge = amount ? `<b>${amount}</b> per ${every}` : "your plan";

  const html = wrap(`
    <h2 style="color:#0f766e;margin:0 0 14px;font-size:22px">Your free trial ends ${when ? `on ${esc(when)}` : "soon"}.</h2>
    <p style="margin:0 0 18px">Nothing has been charged so far. ${when ? `On <b>${esc(when)}</b>` : "When it ends"} your card is charged ${charge}, and the board keeps coming every evening.</p>
    ${btn(app + "/#board", "Open tonight's board →")}
    <p style="margin:0 0 16px"><b>If you'd rather not continue, cancel before then and you pay nothing.</b> Sign in and use <b>Manage billing</b> in the top bar — two clicks, no cancellation fee, no one to email.</p>
    <p style="margin:0 0 22px">We'd rather you stayed because the research is useful to you than because you forgot to cancel.</p>`);

  const text = `Your free trial ends ${when ? "on " + when : "soon"}.

Nothing has been charged so far. ${when ? "On " + when : "When it ends"} your card is charged ${amount ? amount + " per " + every : "your plan"}.

Open the board: ${app}/#board

If you'd rather not continue, cancel before then and you pay nothing — sign in and use "Manage billing" in the top bar.

We'd rather you stayed because the research is useful than because you forgot to cancel.

Keep swinging,
The Slow Swing Team`;

  return { subject: when ? `Your free trial ends ${when}` : "Your free trial ends soon", html, text };
}

// Sent when a charge is declined. Stripe retries for about three weeks and then
// cancels, so the risk isn't losing the money — it's the customer losing access
// one day with no idea why.
function paymentFailedEmail(env, info) {
  const app = env.APP_URL || "https://theslowswing.com";
  const amount = info.amount != null ? `$${(info.amount / 100).toFixed(2)}` : null;

  const html = wrap(`
    <h2 style="color:#0f766e;margin:0 0 14px;font-size:22px">Your card was declined.</h2>
    <p style="margin:0 0 18px">We couldn't take ${amount ? `<b>${amount}</b>` : "your payment"} this time. It happens — expired cards, a bank flagging a new merchant, a changed number.</p>
    <p style="margin:0 0 18px"><b>You still have access.</b> We'll retry automatically over the next few weeks. If none of the retries go through, the subscription ends and the board stops.</p>
    ${btn(app + "/#board", "Update your card →")}
    <p style="margin:0 0 22px">Sign in and use <b>Manage billing</b> in the top bar to update it — that's all it takes.</p>`);

  const text = `Your card was declined.

We couldn't take ${amount || "your payment"} this time. It happens - expired cards, a bank flagging a new merchant, a changed number.

You still have access. We'll retry automatically over the next few weeks. If none of the retries go through, the subscription ends and the board stops.

Sign in and use "Manage billing" in the top bar to update your card: ${app}

Keep swinging,
The Slow Swing Team`;

  return { subject: "Your card was declined — access is still on", html, text };
}

function notifyEmail(email, plan, n, trialEnd, returning) {
  const label = PLAN_LABEL[plan] || plan || "Monthly";
  const subject = returning ? `Repeat signup — ${email}` : `New signup #${n} — ${email} (${label})`;
  const html = `<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0f172a;line-height:1.6">
    <h3 style="margin:0 0 10px;color:#0f766e">${returning ? "Someone signed up again" : "New signup"}</h3>
    <table style="border-collapse:collapse;font-size:14px">
      <tr><td style="padding:3px 14px 3px 0;color:#64748b">Email</td><td><b>${esc(email)}</b></td></tr>
      <tr><td style="padding:3px 14px 3px 0;color:#64748b">Plan clicked</td><td>${esc(label)}</td></tr>
      <tr><td style="padding:3px 14px 3px 0;color:#64748b">Signed up</td><td>${esc(fmtET(new Date()))}</td></tr>
      <tr><td style="padding:3px 14px 3px 0;color:#64748b">Trial ends</td><td>${esc(fmtDate(trialEnd))}</td></tr>
      <tr><td style="padding:3px 14px 3px 0;color:#64748b">Total signups</td><td><b>${n}</b></td></tr>
    </table>
    ${returning ? '<p style="color:#64748b;font-size:13px;margin:14px 0 0">This address already existed — the 30-day clock was NOT reset.</p>' : ""}
  </div>`;
  return { subject, html, text: `${subject}\nPlan: ${label}\nTrial ends: ${fmtDate(trialEnd)}\nTotal: ${n}` };
}

// ---------- magic link ----------
// A 6-digit code issued alongside every magic link. The link signs in the
// browser that opens it; the code signs in the browser where the email was
// typed. Codes exist because corporate mail filters "pre-click" every link to
// scan it — and a one-shot link is spent before the person ever sees it. A
// code cannot be consumed by a scanner. 15-minute life, 5 wrong guesses and
// it dies, and the issuing endpoint is rate-limited, so 6 digits is plenty.
async function signinCode(env, email) {
  const n = crypto.getRandomValues(new Uint32Array(1))[0] % 1000000;
  const code = String(n).padStart(6, "0");
  await env.STORE.put(`code:${normEmail(email)}`, JSON.stringify({ code, tries: 0, iat: Date.now() }), { expirationTtl: 900 });
  return code;
}

async function magicLink(env, email) {
  const nonce = b64url(crypto.getRandomValues(new Uint8Array(16)));
  // Store the nonce so the link can only be redeemed once.
  await env.STORE.put(`nonce:${nonce}`, normEmail(email), { expirationTtl: 900 });
  const token = await signToken({ t: "magic", e: normEmail(email), n: nonce, exp: Date.now() + 15 * 60 * 1000 }, env.SESSION_SECRET);
  return `${env.APP_URL || "https://theslowswing.com"}/api/auth?token=${encodeURIComponent(token)}`;
}

async function currentEmail(request, env) {
  const p = await verifyToken(cookies(request).tss, env.SESSION_SECRET);
  return p && p.t === "session" && p.e ? p.e : null;
}

// ---------- dead-man check ----------
// Runs from Cloudflare's cron (wrangler.toml [triggers]) every weekday evening,
// hours after the nightly publish should have landed. If the board in KV is not
// stamped with today's session, something on the Mac side failed to say so —
// which is exactly the case this exists for: yfinance outage, sleeping Mac,
// failed deploy, power cut, all alike. The Mac cannot be trusted to report its
// own absence; this runs somewhere else. Market holidays cost one false alarm
// each, which is cheaper than one missed real one.
async function deadManCheck(env) {
  const etDate = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());                                   // "YYYY-MM-DD" in New York
  const dow = new Date(etDate + "T12:00:00Z").getUTCDay();
  if (dow === 0 || dow === 6) return { skipped: "weekend" };

  let session = null, generated = null, counts = null;
  try {
    const raw = await env.STORE.get("board:current");
    if (raw) {
      const b = JSON.parse(raw);
      session = b.session_date ? String(b.session_date).slice(0, 10) : null;
      generated = b.generated_at || null;
      counts = b.counts || null;
    }
  } catch (e) {}
  if (session === etDate) return { ok: true, session };

  const subject = `\u26A0\uFE0F STS board NOT updated for ${etDate}`;
  const body = `The board served at theslowswing.com is stamped ${session || "(none)"}` +
    `${generated ? ` (generated ${generated})` : ""}, but today's session is ${etDate}.\n\n` +
    `Either the nightly run on the Mac did not complete, or it completed and did not publish. ` +
    `Check ~/STS/15min/evening.log. If today is a market holiday, ignore this.\n\n` +
    `Re-run by hand:  zsh ~/STS/15min/run_evening.sh`;
  const tasks = [];
  if (env.NOTIFY_EMAIL) {
    tasks.push(sendEmail(env, { to: env.NOTIFY_EMAIL, subject,
      html: `<pre style="font:14px/1.5 -apple-system,Segoe UI,sans-serif;white-space:pre-wrap">${esc(body)}</pre>`,
      text: body }).catch(() => {}));
  }
  // Optional Telegram, the channel that actually gets looked at. Set with:
  //   wrangler secret put TG_TOKEN     wrangler secret put TG_CHAT
  if (env.TG_TOKEN && env.TG_CHAT) {
    tasks.push(fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/sendMessage`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ chat_id: env.TG_CHAT, text: `${subject}\n\n${body}` }),
    }).catch(() => {}));
  }
  await Promise.all(tasks);
  return { ok: false, session, expected: etDate, counts };
}

// ---------- routes ----------
export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(deadManCheck(env));
  },

  async fetch(request, env, ctx) {
    const url = new URL(request.url), p = url.pathname;
    try {
      // Manual dead-man check (GET) for testing; harmless to expose — it only emails the operator.
      if (p === "/api/deadman") return json(await deadManCheck(env));
      if (p === "/api/signup" && request.method === "POST") return await signup(request, env, ctx);
      if (p === "/api/login" && request.method === "POST") return await login(request, env, ctx);
      if (p === "/api/code" && request.method === "POST") return await redeemCode(request, env, ctx);
      if (p === "/api/auth" && request.method === "GET") return await authCallback(request, env);
      if (p === "/api/me" && request.method === "GET") return await me(request, env);
      if (p === "/api/board" && request.method === "GET") return await board(request, env);
      if (p === "/api/logout") return redirect("/", { "set-cookie": clearSession() });
      if (p === "/api/checkout" && request.method === "POST") return await checkout(request, env);
      if (p === "/api/portal" && request.method === "POST") return await portal(request, env);
      if (p === "/api/stripe-webhook" && request.method === "POST") return await stripeWebhook(request, env);
    } catch (e) {
      return json({ error: "Something went wrong on our end. Please try again." }, 500);
    }
    return env.ASSETS.fetch(request);
  },
};

async function rateLimited(request, env, ctx, bucket, max) {
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  const key = `rl:${bucket}:${ip}:${Math.floor(Date.now() / 3600000)}`;
  const hits = parseInt((await env.STORE.get(key)) || "0", 10);
  if (hits >= max) return true;
  ctx.waitUntil(env.STORE.put(key, String(hits + 1), { expirationTtl: 7200 }));
  return false;
}

// Same shape as rateLimited(), keyed by something other than the IP.
async function rateLimitedKey(env, ctx, what, max) {
  const key = `rl:${what}:${Math.floor(Date.now() / 3600000)}`;
  const hits = parseInt((await env.STORE.get(key)) || "0", 10);
  if (hits >= max) return true;
  ctx.waitUntil(env.STORE.put(key, String(hits + 1), { expirationTtl: 7200 }));
  return false;
}

// POST /api/code {email, code} -> session cookie. The code route for people
// whose mail client (or employer) won't let them open the link on this device.
async function redeemCode(request, env, ctx) {
  const body = await request.json().catch(() => ({}));
  const email = normEmail(body.email);
  const code = String(body.code || "").replace(/\D/g, "");
  if (!validEmail(email) || code.length !== 6) return json({ error: "Enter the 6-digit code from the email." }, 400);
  if (await rateLimited(request, env, ctx, "code", 30)) return json({ error: "Too many attempts. Try again later." }, 429);
  const raw = await env.STORE.get(`code:${email}`);
  if (!raw) return json({ error: "That code has expired. Request a new sign-in email." }, 400);
  const rec = JSON.parse(raw);
  if (rec.code !== code) {
    rec.tries = (rec.tries || 0) + 1;
    if (rec.tries >= 5) { await env.STORE.delete(`code:${email}`); return json({ error: "Too many wrong codes. Request a new sign-in email." }, 400); }
    await env.STORE.put(`code:${email}`, JSON.stringify(rec), { expirationTtl: 900 });
    return json({ error: `That code isn't right (${5 - rec.tries} tries left).` }, 400);
  }
  await env.STORE.delete(`code:${email}`);                 // one use
  const ent = entitlement(await getSub(env, email));
  if (!ent.ok) return json({ error: ent.reason === "trial_expired" ? "Your 30-day trial has ended." : "We couldn't find an active account for that email." }, 403);
  const session = await signToken({ t: "session", e: email, exp: Date.now() + 30 * 86400000 }, env.SESSION_SECRET);
  return json({ ok: true }, 200, { "set-cookie": setSession(session) });
}

async function signup(request, env, ctx) {
  if (!env.STORE) return json({ error: "Signup isn't configured yet." }, 501);
  const body = await request.json().catch(() => ({}));
  const email = normEmail(body.email);
  const plan = ["monthly", "annual", "founders"].includes(body.plan) ? body.plan : "monthly";
  if (!validEmail(email)) return json({ error: "Please enter a valid email address." }, 400);
  // Per-IP is loose (phones share carrier IPs; friends share Wi-Fi); per-address is tight.
  if (await rateLimited(request, env, ctx, "signup", 30)) return json({ error: "Too many signups from this connection. Try again later." }, 429);
  if (await rateLimitedKey(env, ctx, `signup:${email}`, 5)) return json({ error: "Too many attempts for this email. Try again in an hour." }, 429);

  const existing = await env.STORE.get(subKey(email));
  const returning = !!existing;
  let rec, count;
  if (returning) {
    rec = JSON.parse(existing);
    count = parseInt((await env.STORE.get("signups:count")) || "0", 10);
  } else {
    const now = Date.now(), end = now + TRIAL_DAYS * 86400000;
    count = parseInt((await env.STORE.get("signups:count")) || "0", 10) + 1;
    rec = {
      email, plan_interest: plan, n: count,
      created_at: new Date(now).toISOString(),
      trial_start: new Date(now).toISOString(),
      trial_end: new Date(end).toISOString(),
      status: "trialing",
    };
    await putSub(env, email, rec);
    await env.STORE.put("signups:count", String(count));
  }

  const trialEnd = new Date(rec.trial_end);
  const ent = entitlement(rec);
  // The welcome / returning email carries a magic link, so the board opens signed in.
  const link = ent.ok ? await magicLink(env, email) : (env.APP_URL || "https://theslowswing.com");
  const code = ent.ok ? await signinCode(env, email) : null;
  const msg = returning ? returningEmail(env, trialEnd, ent.daysLeft || 0, link, code) : welcomeEmail(env, trialEnd, link, code);
  await sendEmail(env, { to: email, subject: msg.subject, html: msg.html, text: msg.text });

  if (env.NOTIFY_EMAIL) {
    const n = notifyEmail(email, plan, rec.n || count, trialEnd, returning);
    ctx.waitUntil(sendEmail(env, { to: env.NOTIFY_EMAIL, subject: n.subject, html: n.html, text: n.text }).catch(() => {}));
  }
  return json({ ok: true });
}

async function login(request, env, ctx) {
  const body = await request.json().catch(() => ({}));
  const email = normEmail(body.email);
  if (!validEmail(email)) return json({ error: "Please enter a valid email address." }, 400);
  if (await rateLimited(request, env, ctx, "login", 10)) return json({ error: "Too many attempts. Try again later." }, 429);

  const sub = await getSub(env, email);
  const ent = entitlement(sub);
  // The HTTP answer never reveals whether an address exists. The EMAIL can —
  // it only reaches the mailbox owner.
  if (ent.ok) {
    const link = await magicLink(env, email);
    const code = await signinCode(env, email);
    const m = loginEmail(link, code);
    await sendEmail(env, { to: email, subject: m.subject, html: m.html, text: m.text });
  } else if (!sub) {
    // Unknown address: say so, once an hour at most per address, so the form
    // can't be used to flood a stranger's inbox.
    if (!(await rateLimitedKey(env, ctx, `noacct:${email}`, 1))) {
      const m = noAccountEmail(env);
      await sendEmail(env, { to: email, subject: m.subject, html: m.html, text: m.text });
    }
  }
  // (known address with expired trial / no access: the link flow already
  //  redirects to the right message; nothing extra here)
  return json({ ok: true });
}

async function authCallback(request, env) {
  const token = new URL(request.url).searchParams.get("token");
  const p = await verifyToken(token, env.SESSION_SECRET);
  if (!p || p.t !== "magic" || !p.e) return redirect("/?signin=expired#board");

  // Burn the nonce — a link works exactly once.
  const holder = p.n ? await env.STORE.get(`nonce:${p.n}`) : null;
  if (!holder || holder !== p.e) return redirect("/?signin=used#board");
  await env.STORE.delete(`nonce:${p.n}`);

  const ent = entitlement(await getSub(env, p.e));
  if (!ent.ok) return redirect(`/?signin=${ent.reason === "trial_expired" ? "expired_trial" : "noaccess"}#board`);

  const session = await signToken({ t: "session", e: p.e, exp: Date.now() + 30 * 86400000 }, env.SESSION_SECRET);
  return redirect("/?signin=ok#board", { "set-cookie": setSession(session) });
}

async function me(request, env) {
  const email = await currentEmail(request, env);
  if (!email) return json({ authed: false });
  const sub = await getSub(env, email);
  const ent = entitlement(sub);
  return json({ authed: true, email, member: ent.ok, status: ent.status, daysLeft: ent.daysLeft,
                // drives the "Manage billing" link — cancellation must be as easy as signing up
                hasSub: !!(sub && sub.customer),
                // the exact date, so the pricing page can promise "no charge until X"
                // without the client guessing it from a day count
                trialEnd: (sub && sub.trial_end) || null });
}

async function board(request, env) {
  const email = await currentEmail(request, env);
  if (!email) return json({ error: "not_signed_in" }, 401);
  const ent = entitlement(await getSub(env, email));
  if (!ent.ok) return json({ error: ent.reason, status: ent.status }, 403);
  const data = await env.STORE.get("board:current");
  if (!data) return json({ error: "board_unavailable" }, 503);
  return new Response(data, {
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

// ---------- Stripe: convert a trial to a paid subscription ----------
async function checkout(request, env) {
  if (!env.STRIPE_SECRET_KEY) return json({ error: "Payments aren't switched on yet." }, 501);
  const email = await currentEmail(request, env);
  if (!email) return json({ error: "not_signed_in" }, 401);

  const body = await request.json().catch(() => ({}));
  const plan = ["monthly", "annual", "founders"].includes(body.plan) ? body.plan : "monthly";
  const price = plan === "founders" ? env.STRIPE_PRICE_FOUNDERS
              : plan === "annual"   ? env.STRIPE_PRICE_ANNUAL
              :                       env.STRIPE_PRICE_MONTHLY;
  if (!price) return json({ error: "no_price_configured" }, 500);

  const sub = await getSub(env, email);

  // Refuse a SECOND subscription. The pricing page already routes existing
  // subscribers to the billing portal, but that is a client-side guard: a browser
  // tab opened before they subscribed still believes they have no subscription,
  // and one click there would create a second $20/mo subscription on the same
  // Stripe customer. Double billing is the worst bug this codebase can have, so
  // the refusal lives on the server where a stale page can't route around it.
  if (sub && sub.subscription && ["active", "past_due"].includes(sub.status)) {
    return json({ error: "already_subscribed" }, 409);
  }

  const params = {
    mode: "subscription",
    line_items: [{ price, quantity: 1 }],
    allow_promotion_codes: true,
    billing_address_collection: "auto",
    success_url: `${env.APP_URL || "https://theslowswing.com"}/?sub=ok#board`,
    cancel_url: `${env.APP_URL || "https://theslowswing.com"}/?sub=canceled#pricing`,
    metadata: { email },
    subscription_data: { metadata: { email } },
  };

  // Carry an in-progress trial ACROSS to Stripe. Never trial_period_days — that
  // would grant a fresh 30 days on top of the ones already given. Instead pin
  // trial_end to the date this person's existing trial already ends: the card is
  // collected now, the first charge lands the day their free days actually run
  // out, and nobody pays for days they were promised for free.
  //
  // Stripe requires trial_end to be at least 48 hours out. Inside that window
  // there is nothing left worth preserving, so bill immediately.
  const ent = entitlement(sub);
  if (ent.ok && ent.status === "trialing" && sub && sub.trial_end) {
    const endsAt = Math.floor(Date.parse(sub.trial_end) / 1000);
    if (isFinite(endsAt) && endsAt > Math.floor(Date.now() / 1000) + 48 * 3600) {
      params.subscription_data.trial_end = endsAt;
      // Card on file, but no charge today — say so on Stripe's own page.
      params.subscription_data.trial_settings = {
        end_behavior: { missing_payment_method: "cancel" },
      };
    }
  }

  if (sub && sub.customer) params.customer = sub.customer;
  else params.customer_email = email;

  const session = await stripeApi(env, "checkout/sessions", "POST", params);
  if (session && session.url) return json({ url: session.url });
  return json({ error: "checkout_failed" }, 400);
}

// ---------- Stripe: billing portal (manage / cancel) ----------
async function portal(request, env) {
  if (!env.STRIPE_SECRET_KEY) return json({ error: "Payments aren't switched on yet." }, 501);
  const email = await currentEmail(request, env);
  if (!email) return json({ error: "not_signed_in" }, 401);
  const sub = await getSub(env, email);
  if (!sub || !sub.customer) return json({ error: "no_subscription" }, 400);
  const s = await stripeApi(env, "billing_portal/sessions", "POST", {
    customer: sub.customer,
    return_url: `${env.APP_URL || "https://theslowswing.com"}/#board`,
  });
  if (s && s.url) return json({ url: s.url });
  return json({ error: "portal_failed" }, 400);
}

// ---------- Stripe -> KV sync ----------
async function stripeWebhook(request, env) {
  const raw = await request.text();
  const ok = await verifyStripeSig(raw, request.headers.get("stripe-signature"), env.STRIPE_WEBHOOK_SECRET);
  if (!ok) return new Response("bad signature", { status: 400 });

  let event;
  try { event = JSON.parse(raw); } catch { return new Response("bad json", { status: 400 }); }
  const obj = (event.data && event.data.object) || {};

  // MERGE, never replace. The KV record carries fields Stripe knows nothing about
  // — created_at, n (signup number), plan_interest, trial_start/trial_end. A blind
  // overwrite here would erase the history of every early subscriber.
  // What Stripe says CHANGED in this event. `customer.subscription.updated` fires
  // for unrelated edits, and a single portal cancellation emits two of them one
  // second apart — one carrying cancel_at, one carrying only the reason the
  // customer typed. Deciding from our own stored record instead means both events
  // can read the same stale value and both send. previous_attributes is the
  // authoritative, stateless answer: the field is present only in the event that
  // actually changed it.
  const changed = (event.data && event.data.previous_attributes) || null;
  const didChange = (...fields) => {
    // Absent previous_attributes (created / deleted / a subscription we fetched
    // ourselves) means "we can't tell" — fall back to comparing with our record.
    if (!changed) return null;
    return fields.some((f) => Object.prototype.hasOwnProperty.call(changed, f));
  };

  async function syncSubscription(subscription) {
    let email = (subscription.metadata && subscription.metadata.email) || null;
    const customerId = subscription.customer || null;
    if (!email && customerId) {
      const cust = await stripeApi(env, `customers/${customerId}`);
      email = cust && cust.email ? cust.email : null;
    }
    if (!email) return;
    const existing = (await getSub(env, email)) || {};
    const newStatus = mapStripeStatus(subscription.status);
    // Send the confirmation exactly once — on the transition INTO active. Stripe
    // fires subscription.updated for all sorts of reasons; without this guard a
    // subscriber gets "you're subscribed" again every time anything changes.
    const justSubscribed = newStatus === "active" && existing.status !== "active"
                           && didChange("status") !== false;
    // Exactly ONE cancellation email per cancellation. Either they scheduled it
    // (cancel_at_period_end flips on and they keep access until the period ends)
    // or it ended outright. When a scheduled cancel later becomes a deletion we
    // have already written to them, so wasEnding suppresses the duplicate.
    const wasEnding = !!existing.cancel_at_period_end;
    const endsAt = subEndsAt(subscription);
    const nowEnding = !!endsAt;
    // Two independent conditions must both hold: the subscription IS winding down
    // now and wasn't before (our record), AND this particular event is the one
    // that changed it (Stripe's record). Either alone has a failure mode; together
    // a duplicate event cannot produce a duplicate email.
    const cancelFieldsMoved = didChange("cancel_at", "cancel_at_period_end", "status");
    const thisEventCancelled = cancelFieldsMoved !== false;   // null = can't tell, allow
    const justScheduledCancel = nowEnding && !wasEnding && newStatus !== "canceled" && thisEventCancelled;
    const justEnded = newStatus === "canceled" && existing.status !== "canceled" && !wasEnding;
    await putSub(env, email, {
      ...existing,
      email: normEmail(email),
      status: newStatus,
      stripe_status: subscription.status,
      customer: customerId || existing.customer || null,
      subscription: subscription.id || existing.subscription || null,
      current_period_end: subPeriodEnd(subscription),
      // normalised: true whenever the subscription is winding down, by either
      // of Stripe's two representations
      cancel_at_period_end: nowEnding,
      cancel_at: endsAt,
      updated_at: new Date().toISOString(),
    });

    if (justSubscribed) {
      let amount = null, interval = null;
      try {
        const item = subscription.items && subscription.items.data && subscription.items.data[0];
        if (item && item.price) {
          amount = item.price.unit_amount;
          interval = item.price.recurring && item.price.recurring.interval;
        }
      } catch (e) {}
      const onTrial = subscription.status === "trialing";
      const m = subscribedEmail(env, { amount, interval, periodEnd: subPeriodEnd(subscription), trialing: onTrial });
      await sendEmail(env, { to: email, subject: m.subject, html: m.html, text: m.text });
      if (env.NOTIFY_EMAIL) {
        await sendEmail(env, { to: env.NOTIFY_EMAIL,
          // Don't call it PAID when no money moved — the inbox is the books.
          subject: onTrial ? `\u{1F193} TRIAL CARD \u2014 ${email}` : `\u{1F4B0} PAID \u2014 ${email}`,
          html: `<p><b>${esc(email)}</b> ${onTrial ? "added a card during their free trial" : "just subscribed"}${amount != null ? ` \u2014 $${(amount/100).toFixed(2)}/${interval||'month'}` : ""}.${onTrial && subPeriodEnd(subscription) ? ` First charge <b>${esc(fmtDate(new Date(subPeriodEnd(subscription)*1000)))}</b>.` : ""}</p>`,
          text: `${email} ${onTrial ? "added a card during their trial" : "just subscribed"}.` }).catch(() => {});
      }
    }

    if (justScheduledCancel || justEnded) {
      const c = canceledEmail(env, { endsAt: justEnded ? null : endsAt, immediate: justEnded });
      await sendEmail(env, { to: email, subject: c.subject, html: c.html, text: c.text });
      if (env.NOTIFY_EMAIL) {
        const when = (!justEnded && endsAt) ? fmtDate(new Date(endsAt * 1000)) : "immediately";
        await sendEmail(env, { to: env.NOTIFY_EMAIL,
          subject: `\u{1F6AA} CANCELED \u2014 ${email}`,
          html: `<p><b>${esc(email)}</b> cancelled. Access ends <b>${esc(when)}</b>.</p>`,
          text: `${email} cancelled. Access ends ${when}.` }).catch(() => {});
      }
    }
  }

  // Resolve the email for any Stripe object that carries a customer.
  async function emailFor(o) {
    let email = (o.metadata && o.metadata.email) || o.customer_email || null;
    if (!email && o.customer) {
      const cust = await stripeApi(env, `customers/${o.customer}`);
      email = cust && cust.email ? cust.email : null;
    }
    return email ? normEmail(email) : null;
  }

  // One send per key, ever. Stripe retries a failed delivery and fires repeat
  // events during dunning; without this the same warning lands repeatedly.
  async function sendOnce(key, to, msg) {
    const k = `sent:${key}`;
    if (await env.STORE.get(k)) return false;
    await env.STORE.put(k, "1", { expirationTtl: 60 * 60 * 24 * 120 });
    await sendEmail(env, { to, subject: msg.subject, html: msg.html, text: msg.text });
    return true;
  }

  async function warnTrialEnding(subscription) {
    const email = await emailFor(subscription);
    if (!email) return;
    let amount = null, interval = null;
    const item = subscription.items && subscription.items.data && subscription.items.data[0];
    if (item && item.price) {
      amount = item.price.unit_amount;
      interval = item.price.recurring && item.price.recurring.interval;
    }
    const endsAt = subscription.trial_end || subPeriodEnd(subscription);
    const m = trialEndingEmail(env, { endsAt, amount, interval });
    await sendOnce(`trialend:${subscription.id}:${endsAt}`, email, m);
  }

  async function warnPaymentFailed(invoice) {
    const email = await emailFor(invoice);
    if (!email) return;
    const m = paymentFailedEmail(env, { amount: invoice.amount_due });
    const sent = await sendOnce(`payfail:${invoice.id}`, email, m);
    if (sent && env.NOTIFY_EMAIL) {
      await sendEmail(env, { to: env.NOTIFY_EMAIL,
        subject: `\u26A0\uFE0F CARD DECLINED \u2014 ${email}`,
        html: `<p><b>${esc(email)}</b> had a payment decline${invoice.amount_due != null ? ` \u2014 $${(invoice.amount_due/100).toFixed(2)}` : ""}. Stripe will retry, then cancel.</p>`,
        text: `${email} had a payment decline.` }).catch(() => {});
    }
  }

  try {
    switch (event.type) {
      case "checkout.session.completed":
        if (obj.subscription) {
          await syncSubscription(await stripeApi(env, `subscriptions/${obj.subscription}`));
        }
        break;
      case "customer.subscription.created":
      case "customer.subscription.updated":
      case "customer.subscription.deleted":
        await syncSubscription(obj);
        break;

      // Fires ~3 days before a trial converts.
      case "customer.subscription.trial_will_end":
        await warnTrialEnding(obj);
        break;

      // Fires on a declined charge, and again on each failed retry — so guard it
      // by invoice id, or a customer gets the same warning three times.
      case "invoice.payment_failed":
        await warnPaymentFailed(obj);
        break;

      default:
        break;
    }
  } catch (e) {
    // Signature already verified, so this is our own hiccup. Return 200 so Stripe
    // doesn't hammer retries; the next event for this subscription will re-sync.
    return new Response("handled-with-warning", { status: 200 });
  }
  return new Response("ok", { status: 200 });
}
