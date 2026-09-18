// The Slow Swing — blog posts. THIS FILE IS THE ONLY PLACE POSTS LIVE.
// index.html loads it with <script src="posts.js"> before its own script.
//
// Editing rules (they exist because a post was once destroyed by two chats
// editing the same file):
//   * Blog work edits ONLY this file. Site/UI work edits ONLY index.html.
//   * Edit in place on the Mac (or re-stage immediately before editing and
//     commit with the mtime guard). Never write from an old copy. Never force.
//   * Newest post first. cat.cls = start|case|lesson|note.
//   * After editing, check it parses:  node -e "require('./site/posts.js')"
//     (it just defines POSTS; nothing else runs).
const POSTS = [
  {
    slug:'why-percentages-not-prices', cat:{label:'Start Here', cls:'start'}, icon:'📐', sample:false,
    author:'GJ Singh', date:'Sep 17, 2026', read:'4 min read',
    title:'Why we show moves, not prices',
    excerpt:'Every figure on this site is a percentage from the signal date, never a dollar price. Part of that is our data licence. The larger part is that the move is simply the better unit for judging a setup.',
    body:`<p>Look anywhere on this site and you will find moves rather than money. Every name on the board, every row in the Track Record, every figure in these posts is a percentage measured from its signal date. You will not find a dollar price.</p>
    <p>There are two reasons for that, and they are worth separating, because only one of them is about us.</p>
    <h2>The first reason is the licence</h2>
    <p>Our market data licence covers using prices to compute our research. It does not cover republishing them. One sentence, and that is the whole of it.</p>
    <h2>The second reason is that the move is the better unit anyway</h2>
    <p>This is the part that would still be true if the licence said something entirely different, and it is the part worth your attention.</p>
    <p>A $700 stock and a $25 stock cannot be compared in dollars. A two dollar move is a rounding error in one and a serious event in the other. Put them in the same table in dollars and the table tells you nothing. Put them in percentages and they sit side by side honestly, which is exactly what the Track Record has to do across every name we have ever flagged.</p>
    <p>Two figures from posts already in this journal make the point. Sandisk (<a class="tklink" data-post="hold-the-dip-sndk">SNDK</a>) reached roughly <b class="up">+30%</b> at its peak. Capri (<a class="tklink" data-post="earnings-risk-cpri">CPRI</a>) sat about <b class="down">16%</b> below its signal four weeks in. Those two numbers can be set against each other directly, and you learn something from the comparison. The two share prices could not be compared at all.</p>
    <p>A dollar figure also pulls the eye toward the wrong thing. Knowing a stock is trading at 412 tells you nothing about whether the setup is doing what it was flagged for. Knowing it sits 6% above its signal, having dipped 3% along the way, tells you precisely that. <span style="color:var(--primary);text-decoration:underline;text-decoration-color:var(--primary);text-underline-offset:3px;font-weight:600">The setup was never about the price. It was always about the move.</span></p>
    <h2>Which is really a psychology point in disguise</h2>
    <p>Our <a data-nav="psychology" style="color:var(--primary); font-weight:600">Trading Psychology</a> page makes a related argument at length: a $100 loss on a $1,000 position and a $10,000 loss on a $100,000 position are identical in percentage terms and feel nothing alike. The dollar figure is what rattles people out of sound positions. The percentage is what tells them whether anything has actually gone wrong.</p>
    <p>Reading the board in percentages is a small, daily rehearsal of that discipline. It keeps your attention on the size of the move relative to what you committed, which is the only version of the number that carries information.</p>
    <h2>Nothing here is being withheld</h2>
    <p>The price of any name on any date is about ten seconds away. Your brokerage account has it, with the date, on a chart, for free. Any charting site has it. We publish the ticker and the signal date, which is everything you need to look it up yourself, and we would rather you did look, because checking our work is a good habit and we have no interest in discouraging it.</p>
    <p>There is a different set of numbers we will never publish, in any unit, and that is deliberate: an entry price, an exit, a price target, a position size. Those are not data, they are instructions, and instructions would make this personalised advice rather than research. We are not registered to give advice and have no intention of drifting into it. We show you where conditions look ripe and how the move has behaved since. What you do about it stays yours.</p>
    <p>Figures cited above are from a paper tracked, hypothetical record as of this post's date, and the site's live numbers will move on from them. They are levels a price reached, not returns anyone earned. Educational research, not advice.</p>`
  },
  {
    slug:'earnings-both-ways-zs', cat:{label:'Case Study', cls:'case'}, icon:'🛡️', sample:false,
    author:'GJ Singh', date:'Sep 14, 2026', read:'4 min read',
    title:'When earnings went the other way (ZS)',
    excerpt:'Zscaler was flagged three separate times around one earnings report. One signal sailed through it, one was rescued by it, and one came after it and ran. Same name, same setup, three different stories.',
    body:`<p>A few weeks ago we wrote up Capri (<a class="tklink" data-post="earnings-risk-cpri">CPRI</a>), a setup that was working right up until the company reported earnings and gave the whole move back. This is that story with the sign reversed, and the two are worth reading side by side.</p>
    <p>Zscaler (<a class="tklink" data-nav="board">ZS</a>) has appeared on our board three separate times since July, and its quarterly report on <strong>September 3</strong> sits in the middle of those three signals. What separated them had very little to do with how the setups looked and almost everything to do with that one date on the calendar.</p>
    <div class="journeycard">
      <div class="jchips"><span class="jchip watch">◆ Watch</span><span class="jchip">Phoenix setup</span><span class="jchip">GREEN regime at add</span><span class="jchip earn">📅 Earnings Sep 3</span></div>
      <div class="jwrap" data-journey="zs"></div>
      <div class="jcap">Flagged five sessions after the report, a shallow dip, then about <b class="up">+17%</b> at its peak inside the first week. Still open.</div>
    </div>
    <h2>Three signals, one report</h2>
    <p>The <strong>July 20</strong> signal was the easy one. It was flagged well before the report, went about 5% underwater at its worst, and by the four week mark had reached roughly <b>+25%</b>, with a peak near <b>+32%</b>. Nothing about the September report was knowable when it was flagged. It simply never got in the way.</p>
    <p>The <strong>August 14</strong> signal was the painful one. It was added while the market dial read <strong>Extended</strong>, and it fell about <b class="down">16%</b> below the signal price over the following three weeks. Anyone still holding it went into the September 3 report deeply underwater. The report was strong, the stock gapped higher, and four weeks after the signal it sat at roughly breakeven. Earnings did not make that signal a winner. It rescued it from being a loser.</p>
    <p>The <strong>September 8</strong> signal came five sessions after the report, once the initial pop had faded back. It has dipped only about 4% at its worst and has since reached about <b>+17%</b> at its peak. It is still open, so those figures can and will move.</p>
    <h2>What a setup can and cannot see</h2>
    <p>None of the three signals predicted the earnings report. They cannot. A price based setup reads what the market has already done with a stock. It has no view on what a company is about to say, and no view at all on how the market will choose to react to what it says. That holds whether the outcome is pleasant, as it was here, or ugly, as it was with Capri (<a class="tklink" data-post="earnings-risk-cpri">CPRI</a>).</p>
    <p>What the record does show is that conditions kept reading as ripe across eight weeks, at three different prices, on both sides of a quarterly report. That persistence is context worth having. It is not a forecast of the number.</p>
    <h2>Where the confidence actually comes from</h2>
    <p>If a setup cannot see the report, the only thing that helps anyone sit through one is what they believe about the business underneath. That is the job of the quality gate: it asks whether the company is sound enough that a bad quarter is a setback rather than a broken thesis. Worth naming honestly, though, is that Zscaler cleared that gate only at the ◆ Watch level, a notch below the 💎 names. The gate is not why this one worked.</p>
    <p>And here is the part that stops this from being a tidy lesson. A good share of the September move came from a sector wide rally in cybersecurity that had nothing to do with the company results and nothing to do with the setup. We flagged a name, and then a catalyst nobody on our side saw coming arrived four days later. <span style="color:var(--primary);text-decoration:underline;text-decoration-color:var(--primary);text-underline-offset:3px;font-weight:600">A winner you could not have predicted is still a winner you could not have predicted.</span> One good outcome is a data point, not a method.</p>
    <p>So the takeaway is the same one Capri (<a class="tklink" data-post="earnings-risk-cpri">CPRI</a>) handed us, seen from the comfortable side. Know when the names you are watching report. Decide in advance whether you are holding a business for the coming weeks or taking a position on a binary event, because those are two different games with two different risk budgets, and the damage usually comes from mixing them. Earnings dates are public, and they remain the one thing on the calendar that can make or break an otherwise good setup in a single session.</p>
    <p>Paper and hypothetical throughout, as always. These are levels a tracked signal reached, not returns anyone earned, and the September signal is still open. Educational only, and not advice.</p>`
  },
  {
    slug:'welcome', cat:{label:'Start Here', cls:'start'}, icon:'📖', sample:false,
    author:'GJ Singh', date:'Aug 20, 2026', read:'3 min read',
    title:'Welcome to the The Slow Swing Journal — and how to read it',
    excerpt:'What this space is for, what it is not, and the one rule that governs everything published here.',
    body:`<p>This journal is the teaching side of The Slow Swing. The board shows you <em>what</em> the model flagged tonight; the journal is where we slow down and study <em>how</em> these setups actually behave once they arrive — a clean winner, a painful loser, a turnaround — so that over time you read the board with more judgment and less guesswork.</p>
    <p>Every piece here is written <em>after the fact</em>, in the past tense, about a paper-tracked record. You will never find an entry price, an exit, a target, or the words "buy this" — not because we are being coy, but because the moment research becomes a personal instruction it stops being research. What you do with any of it is your decision.</p>
    <blockquote>We scout the fat pitches. The swing is yours.</blockquote>
    <p>When we walk through a name we use the same language as the board — the <strong>signal date</strong>, the <strong>quality gate</strong> (💎 High-Quality / ◆ Watch / △ Higher-risk), the <strong>market regime</strong> at entry, and the <strong>Setup Scorecard</strong>'s peak and worst dip. If any of that is unfamiliar, the <a data-nav="how" style="color:var(--primary); font-weight:600">How it works</a> page is the place to start. All figures are paper / hypothetical during this live validation — a level the price reached, not a return anyone earned.</p>`
  },
  {
    slug:'how-to-use-this', cat:{label:'Start Here', cls:'start'}, icon:'🧭', sample:false,
    author:'GJ Singh', date:'Sep 12, 2026', read:'8 min read',
    title:'How to actually use this board — a first-month playbook',
    excerpt:'Not a system to follow, but a way to build confidence in one. Start smaller than feels interesting, take fewer setups than you want to, and let the first few finish before you scale.',
    body:`<p>The board tells you where conditions look ripe. It cannot tell you how much to risk, when to sell, or whether you'll hold your nerve when a name goes red — and those three things will decide your results far more than which name you picked.</p>
    <p>So this piece isn't a system to copy. It's about the first month: <strong>how to build genuine confidence in an unfamiliar approach without paying tuition you can't afford.</strong> Everything below is a principle or a question for you to answer. None of it is a recommendation, and there isn't a number in here you should treat as one.</p>

    <h2>1. Start smaller than feels interesting</h2>
    <p>The most common way people fail with a new approach isn't picking wrong. It's sizing so large that the first ordinary drawdown makes a calm decision impossible. At the right size you can watch a position go against you and think clearly. At the wrong size you can't, and you'll sell at the worst moment — not because the setup failed, but because the position was too big to hold.</p>
    <p>The test worth applying before your first position: <strong>if this went to zero, would it change anything about my month?</strong> If the answer is yes, it's too big. A first position should be boring enough that being wrong is a lesson rather than an event.</p>
    <blockquote>Your first goal isn't a return. It's a sample of your own behaviour that you can trust.</blockquote>
    <p>There's a second reason to start small that has nothing to do with money. You're gathering evidence about <em>yourself</em> — whether you can sit through a dip, whether you actually check the board nightly, whether this style suits your temperament. That evidence is only useful if collected at a size where you behave normally.</p>

    <h2>2. You almost never need to rush</h2>
    <p>New subscribers often feel that a name appearing on the board is a starting gun — that hesitating means missing it. The retired book says otherwise. Across the completed setups, <strong>about 95% traded more than 1% below their signal level at some point</strong> before doing anything good. Nearly every setup, including the ones that went on to work well, gave you a stretch where it looked worse than the day it appeared.</p>
    <p>That fact is worth sitting with, because it cuts two ways. It means <strong>chasing a name the moment it appears is rarely necessary</strong> — the board isn't a countdown. And it means that a position showing red in its first week is behaving completely normally, not failing. Both halves are the same statistic, and both are easier to believe before you're in the trade than after.</p>

    <h2>3. Take fewer setups than you want to</h2>
    <p>On a busy night the board may show dozens of names. The instinct is to treat that as a shopping list. It isn't — it's the full set of conditions the model flagged, and no one is expected to act on all of them.</p>
    <p>While you're learning, there's a case for narrowing hard rather than spreading wide. The cohort with the most evidence behind it is <strong>Phoenix setups that also cleared the 💎 quality gate</strong> — that's where the strongest live numbers sit, and more usefully, it's where you have the most reason to stay calm when a position goes against you. The quality gate exists precisely to separate a sound business having a rough month from a broken one. Conviction is much easier to hold when you know which you're holding.</p>
    <p>Two or three positions you actually understand will teach you more in a month than twelve you're only half-watching.</p>

    <h2>4. Decide your exit before you enter — and make it yours</h2>
    <p>We don't publish exits, and that isn't coyness. <a data-nav="blog" style="color:var(--primary); font-weight:600">The numbers make the case plainly</a>: nearly nine in ten Phoenix setups reached +5% at some point, but far fewer were still up when their four weeks were done. The gap between those two figures isn't entry quality — every one of those was a winner at some moment. It's the exit.</p>
    <p>What we can give you is the shape of the data so you can choose your own rule. Across retired setups, <strong>Cruise setups reached a median peak near +11% in about 12 days; Phoenix setups near +19% in about 18 days</strong>. Those are hypothetical peaks, not returns anyone captured — but they tell you roughly where these moves tend to run out, and that the two profiles run out in different places.</p>
    <p>The questions only you can answer: at what point does an unrealised gain become real to you? Are you willing to give back some of a peak in exchange for the chance at more? Would you rather be right often and small, or occasionally large? <strong>Write your answer down before you're in the position</strong>, because you will not think clearly about it once you are.</p>

    <h2>5. Let the market backdrop set your pace</h2>
    <p>The market-context read at the top of the board isn't a trade trigger, but it is a reasonable input into how aggressive to be while you're learning. Leaning in hardest when the backdrop looks most stretched is a way to collect an unrepresentative first impression — of the approach, and of yourself.</p>

    <h2>6. Repeat before you scale</h2>
    <p>Take two or three positions. Let them finish, whatever finishing means under the rule you wrote down. Then look at what actually happened — not just the outcome, but your behaviour. Did you hold through the dip? Did you sell early out of discomfort and then watch it run? Did you follow your own rule, or improvise?</p>
    <p>That review is the entire point of the first month. Size up only after you've seen yourself behave well at least a few times — not because a few wins prove the approach works, but because they prove <em>you can execute it.</em> Those are different things, and the second is the one that's actually in your control.</p>

    <h2>The part we don't do</h2>
    <p>We publish research. We don't execute anything. Once you've identified a name here, the trade happens in your own brokerage account, on your own judgement, with your own money — we never see it, never touch it, and never know whether you acted. That separation is deliberate and permanent.</p>
    <p>Which means the honest summary of this whole piece is short: <strong>we scout the fat pitches, and the swing is yours.</strong> The board can put a good pitch in front of you. Whether you swing, how hard, and when you stop running — that was always going to be the part that decides your results.</p>
    <p style="color:#64748b; font-size:13px; margin-top:18px"><em>The Slow Swing is educational research, not investment advice, and nothing above is a recommendation to buy or sell any security or a suggestion about how much to risk. We are not a broker-dealer or investment adviser. All figures are from a paper-tracked, hypothetical record — levels a price reached, not returns anyone earned. Do your own research, and consider speaking with a licensed professional about your own circumstances.</em></p>`
  },
  {
    slug:'exits-play-a-role', cat:{label:'Lesson', cls:'lesson'}, icon:'🚪', sample:false,
    author:'GJ Singh', date:'Sep 6, 2026', read:'6 min read',
    title:'Exits play a role: an entry only pays if the exit is good',
    excerpt:'Across 157 completed paper setups, the vast majority reached a real gain at some point. Whether that gain became anything depended on the half of the trade the model never touches — the exit. That part is yours.',
    body:`<p>We spend most of this journal on the entry — which names the model flags, why a setup looks ripe, what the quality gate is doing. That is only half of a trade. A setup can hand you a genuine opportunity and you can still walk away with nothing, because <strong>an entry only makes money if the exit is good</strong>. Both are required. This piece is about the half we deliberately do not decide for you.</p>
    <p>Start with what the completed paper book actually shows. Across <strong>157 retired setups</strong> — every name we tracked to completion, winners and losers alike — here is how often the price reached a real gain at <em>some</em> point after the signal:</p>
    <div style="overflow-x:auto;margin:18px 0">
      <table style="border-collapse:collapse;width:100%;font-size:14px;min-width:440px">
        <thead>
          <tr style="background:var(--primary);color:#fff">
            <th style="text-align:left;padding:9px 12px;border:1px solid #0e6b63">Cohort</th>
            <th style="text-align:center;padding:9px 12px;border:1px solid #0e6b63">Touched&nbsp;+5%</th>
            <th style="text-align:center;padding:9px 12px;border:1px solid #0e6b63">Touched&nbsp;+10%</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style="padding:9px 12px;border:1px solid #e2e8f0"><b style="color:var(--phoenix)">Phoenix</b> <span style="color:#64748b">(n=120)</span></td>
            <td style="text-align:center;padding:9px 12px;border:1px solid #e2e8f0"><b class="up">89%</b></td>
            <td style="text-align:center;padding:9px 12px;border:1px solid #e2e8f0"><b class="up">76%</b></td>
          </tr>
          <tr style="background:#f8fafc">
            <td style="padding:9px 12px;border:1px solid #e2e8f0"><b style="color:var(--cruise)">Cruise</b> <span style="color:#64748b">(n=37)</span></td>
            <td style="text-align:center;padding:9px 12px;border:1px solid #e2e8f0"><b class="up">84%</b></td>
            <td style="text-align:center;padding:9px 12px;border:1px solid #e2e8f0">51%</td>
          </tr>
          <tr>
            <td style="padding:9px 12px;border:1px solid #e2e8f0"><b>Combined</b> <span style="color:#64748b">(n=157)</span></td>
            <td style="text-align:center;padding:9px 12px;border:1px solid #e2e8f0"><b class="up">88%</b></td>
            <td style="text-align:center;padding:9px 12px;border:1px solid #e2e8f0"><b class="up">70%</b></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p>Read the top row slowly, because it is remarkable. Nearly <strong>nine in ten Phoenix setups reached at least +5%</strong> at some point, and about three in four reached +10%. The setups, on this evidence, are doing their job: they put you in front of names that go on to trade higher far more often than not. If the entry were the whole game, this would be a solved problem.</p>
    <h2>The gap the table hides</h2>
    <p>Now the uncomfortable half. "Touched +5%" means the price <em>reached</em> that level at some point — it is the peak, the MFE, the best the trade ever looked. It is not what you were sitting on at the four-week mark. When we line those two up for the Phoenix names, the gap appears: about <strong>89% touched +5%, but only roughly seven in ten were still above the signal at the four-week close.</strong> Same setups. The difference between those two numbers is not entry quality — every one of those trades was, at some moment, a winner. The difference is <strong>what happened between the peak and the finish line</strong>. That gap is the exit.</p>
    <blockquote>The model can find the pitch. It cannot take the swing for you — and it cannot decide when to stop running.</blockquote>
    <p>This is the entire point. A setup that touches +12% and a setup that touches +12% and then rounds all the way back to flat show up <em>identically</em> in the "touched +10%" column. To the entry, they are the same trade. To your account, they are night and day. The variable that separates them is the one thing a price-based setup never sees: the decision to do something with a gain while it is there.</p>
    <h2>Cruise makes the same point in a different accent</h2>
    <p>Look at the Cruise row. These are quality names taking a breather inside an existing uptrend, and they behave exactly as that description suggests: <strong>84% touched +5%, but only about half reached +10%.</strong> Cruise setups tend to pop a modest amount and then stall — a clean, smaller move rather than a long run. <span style="color:var(--primary);text-decoration:underline;text-decoration-color:var(--primary);text-underline-offset:3px;font-weight:600">That is not a flaw; it is the character of the setup.</span> But it changes the exit problem completely. On a name that historically gives you a brisk +6% and then goes sideways, the cost of waiting for a Phoenix-sized move is watching the gain you already had drain away. Different setup, different rhythm, different exit temperament — and the board tells you which one you are holding.</p>
    <h2>Why we will not hand you the exit</h2>
    <p>You will notice we have not given you a rule — no "take profits at +8%," no trailing stop, no time limit. <span style="color:var(--primary);text-decoration:underline;text-decoration-color:var(--primary);text-underline-offset:3px;font-weight:600">That is deliberate, and it is not evasion.</span> The moment we print a specific exit, this stops being research and becomes a personal instruction, which we are not in the business of giving. But it is also true on the merits: <strong>the right exit is a function of your goals, your position size, your temperament, and how much of a round-trip you can stomach</strong> — none of which we know. A retiree protecting capital and a 30-year-old building it should not run the same exit, even on the identical signal.</p>
    <p><span style="color:var(--primary);text-decoration:underline;text-decoration-color:var(--primary);text-underline-offset:3px;font-weight:600">So think of the exit as your homework, and take it as seriously as you take the entry.</span> Some questions worth settling <em>before</em> you are in a trade, when you can think clearly: Do you want a smooth Phoenix-style runner or a quick Cruise-style pop, and does your exit match? At what point does an unrealized gain become real to you? What size lets you sit through the ordinary dip without flinching? There are no universal answers, and that is the honest reason we do not publish one. What we can tell you is that the data settles the question of <em>whether</em> the exit matters. It plainly does — it is the difference between the peak and the paycheck.</p>
    <p>The setups are meaningful. They earn their keep on the entry side, and the numbers above are the receipt. But a good entry with a careless exit is just a story about a gain you used to have. Get both halves right. We will keep surfacing the pitches — the swing, and knowing when to stop running, stays yours.</p>
    <p style="color:#64748b;font-size:13px;margin-top:18px"><em>All figures are from a paper-tracked, hypothetical record during live validation — a level the price reached, not a return anyone earned, and not advice.</em></p>`
  },
  {
    slug:'clean-winner-nflx', cat:{label:'Case Study', cls:'case'}, icon:'🎬', sample:false,
    author:'GJ Singh', date:'Aug 29, 2026', read:'4 min read',
    title:'What a clean winner looks like (NFLX)',
    excerpt:'Netflix is the shape you hope for — a quality setup that simply worked, with barely a dip to sit through.',
    body:`<p>Not every setup is a nail-biter. Some just work. Netflix is a clean example of the shape you are hoping for when a signal appears, so it is worth studying what "boring and right" looks like before we get to the messier lessons.</p>
    <p>When the signal printed, Netflix was a <strong>Phoenix</strong> setup — a quality name that had pulled back and was steadying — and it cleared the fundamental quality gate with a 💎. The market backdrop was healthy (a <strong>GREEN</strong> regime) the day it was added. Nothing exotic; the checklist simply lined up.</p>
    <div class="journeycard">
      <div class="jchips"><span class="jchip pass">💎 High-Quality</span><span class="jchip">Phoenix setup</span><span class="jchip">GREEN regime at add</span></div>
      <div class="jwrap" data-journey="nflx"></div>
      <div class="jcap">A shallow ~2% dip, then a steady climb — about <b class="up">+13%</b> four weeks after the signal.</div>
    </div>
    <p>What happened next was almost uneventful, in the best way. The setup drifted higher, never dipping more than about 2% below where it started, and four weeks later sat around +13%, having peaked near +14%. No gut-check, no deep drawdown to endure — just a steady grind.</p>
    <h2>Why show a boring winner?</h2>
    <p>Because it calibrates expectations. This is what it looks like when a quality setup works in a supportive regime and nothing interrupts it. It will not always be this smooth — the Sandisk (<a class="tklink" data-post="hold-the-dip-sndk">SNDK</a>) and Capri (<a class="tklink" data-post="earnings-risk-cpri">CPRI</a>) stories are proof — but a shallow-dip, steady-climb name like this is exactly the template the framework is built to surface. And notice: that "peak" is a high the price <em>touched</em>, not a return anyone pocketed. What you do with a move like this is always yours.</p>`
  },
  {
    slug:'hold-the-dip-sndk', cat:{label:'Case Study', cls:'case'}, icon:'💾', sample:false,
    author:'GJ Singh', date:'Aug 27, 2026', read:'5 min read',
    title:'The dip was the toll, not the verdict (SNDK)',
    excerpt:'Sandisk fell about 29% before it did anything right — then finished up about 27%. Why the quality gate is what let you hold.',
    body:`<p>Sandisk did the frightening thing first. After the setup appeared it did not glide higher — it fell, and kept falling, down about <strong>29%</strong> at its worst and still deep in the red (about −9%) a full two weeks in. This is the trade that tests you. Every instinct says cut it.</p>
    <div class="journeycard">
      <div class="jchips"><span class="jchip pass">💎 High-Quality</span><span class="jchip">Phoenix setup</span><span class="jchip">GREEN regime at add</span></div>
      <div class="jwrap" data-journey="sndk"></div>
      <div class="jcap">Down about <b class="down">29%</b> before it turned — and finished about <b class="up">+27%</b> four weeks after the signal.</div>
    </div>
    <p>Here is why the framework said you could sit still: Sandisk had cleared the fundamental quality gate with a 💎. The whole point of that gate is to separate a sound business having a rough month from a broken one — and it is precisely the sound ones you can hold through a drawdown, because the odds favor a recovery.</p>
    <p>And recover it did. By the four-week mark Sandisk was not merely back to even — it was up about +27%, having peaked near +30%. The 29% dip was the toll, not the verdict.</p>
    <h2>The honest caveat</h2>
    <p>Not every dip comes back — the Capri (<a class="tklink" data-post="earnings-risk-cpri">CPRI</a>) story is a setup that fell and <em>stayed</em> down. The quality gate tilts the odds in your favor; it is not a guarantee, and this is a paper-tracked, hypothetical record. But Sandisk is the cleanest illustration of the idea the whole system is built around: in a genuinely sound business, the drawdown is usually the price of admission, not a reason to fold.</p>`
  },
  {
    slug:'earnings-risk-cpri', cat:{label:'Case Study', cls:'case'}, icon:'👜', sample:false,
    author:'GJ Singh', date:'Aug 25, 2026', read:'5 min read',
    title:'A good setup ran straight into earnings (CPRI)',
    excerpt:'Capri climbed +7% — in a healthy regime — then reported earnings and gave it all back. The one risk a price setup cannot see.',
    body:`<p>This one stings in an instructive way, because the setup was not wrong — at least not at first. Capri Holdings was flagged as a <strong>Phoenix</strong> setup on July 30, in a healthy <strong>GREEN</strong> regime, and over its first four sessions it did exactly what you would hope: it climbed about <strong>+7%</strong>.</p>
    <p>Then it reported earnings.</p>
    <div class="journeycard">
      <div class="jchips"><span class="jchip watch">◆ Watch</span><span class="jchip">Phoenix setup</span><span class="jchip">GREEN regime at add</span><span class="jchip earn">📅 Earnings Aug 5</span></div>
      <div class="jwrap" data-journey="cpri"></div>
      <div class="jcap">Up into earnings, then gapped down — about <b class="down">−16%</b> four weeks after the signal.</div>
    </div>
    <p>Capri released quarterly results on <strong>August 5, 2026</strong> — right at the setup's peak — and the stock gapped down hard. Four weeks after the signal it sat about −16%, having round-tripped the gain and then some.</p>
    <h2>What actually went wrong — and what didn't</h2>
    <p>Notice what we can rule out. The market regime was GREEN when Capri was added, so this was not a case of leaning into a weak tape — the broad market was fine. And the setup itself worked in the short run; the name rose before it fell. The single variable that broke the trade was a <strong>scheduled earnings report</strong> landing in the middle of the hold.</p>
    <p>That is the lesson worth internalizing: a healthy regime shields you from market-wide weakness, but it does nothing about single-name <em>event</em> risk. Earnings is binary — a company can beat or miss no matter how clean the chart looks — and it is the one risk a price-based setup simply cannot see. It is also worth noting Capri cleared the quality gate only at the ◆ Watch level, a notch below the 💎 names in the Netflix (<a class="tklink" data-post="clean-winner-nflx">NFLX</a>) and Sandisk (<a class="tklink" data-post="hold-the-dip-sndk">SNDK</a>) stories.</p>
    <p>And earnings are genuinely unpredictable — not just the number, but the <em>reaction</em> to it. A company can beat on both revenue and profit and still fall, because guidance disappointed, or the good news was already priced in, or the market simply decided to sell the news. A strong report is not a green light; the reaction to it is its own coin flip.</p>
    <p>Which points to the real boundary this story is about: <strong>if you hold through an earnings report, you are trading earnings — and that is a different game from investing.</strong> These setups are built for the swing and position timeframe: own a sound business while its price is temporarily out of favor and give it weeks to recover. Sitting through an earnings print is a short, binary event bet. Both can be legitimate on their own terms, but they are not the same discipline — and the way people get hurt is by mixing them: taking an investing-sized position and then subjecting it to trading-sized event risk. If you are going to play the earnings, play it <em>as a trade</em>, with a trade's size and rules — and decide which game you are in <em>before</em> the report, not after.</p>
    <p>We do not tell anyone to sell before a report — that would be advice, and timing is yours. The takeaway is simpler, and it is homework rather than a signal: know when the names you are watching report, and decide, in advance, whether you are investing or trading the event. Earnings dates are public.</p>`
  },
  {
    slug:'patience-flat-swks', cat:{label:'Case Study', cls:'case'}, icon:'⏳', sample:false,
    author:'GJ Singh', date:'Aug 22, 2026', read:'4 min read',
    title:'When nothing happens for two weeks (SWKS)',
    excerpt:'Skyworks went sideways for two weeks — a dud, if you watched it daily — then moved to about +18%. The setup can tell you a name is ripe; it cannot tell you when.',
    body:`<p>Some setups reward you immediately. This one made you wait. Skyworks was flagged on July 20 — a <strong>Phoenix</strong> setup that cleared the quality gate with a 💎, in a healthy <strong>GREEN</strong> regime — and then it did almost nothing. For two full weeks it drifted sideways, never more than a few percent either side of where it started. If you were checking the ticker every day, it would have felt like a dud.</p>
    <div class="journeycard">
      <div class="jchips"><span class="jchip pass">💎 High-Quality</span><span class="jchip">Phoenix setup</span><span class="jchip">GREEN regime at add</span></div>
      <div class="jwrap" data-journey="swks"></div>
      <div class="jcap">Two weeks of going nowhere, then a sharp move — about <b class="up">+13%</b> by the four-week mark.</div>
    </div>
    <p>Then, in the third week, it moved — and quickly. By August 10 it had reached about <b>+18%</b>, and four weeks after the signal it still sat around +13%. The patience <em>was</em> the trade.</p>
    <h2>The setup says "ripe." It does not say "today."</h2>
    <p>This is the honest limit of any setup, ours included: it can flag that a name's conditions look ripe, but it cannot tell you <em>when</em> the move will start. Sometimes it is the next session. Sometimes it is two or three weeks of flat, boring, sideways action first — the stretch that quietly shakes out impatient holders right before the move they were waiting for.</p>
    <p>It is also why the framework holds for weeks and deliberately avoids tight, time-based exits. Cutting a "boring" name at the two-week mark because nothing has happened yet is one of the most reliable ways to miss the move that was about to start. Flat is not the same as failed. (The <a data-nav="psychology" style="color:var(--primary); font-weight:600">Trading Psychology</a> page goes deeper on the discipline of sitting still.)</p>
    <p>The honest caveat, as always: not every flat name eventually pops — some just stay flat, or fade, and those show up in the record too. Waiting tilts the odds when the quality gate says the business underneath is sound; it is not a promise. Paper / hypothetical — a level the price reached, not a return anyone earned, and not advice.</p>`
  },
  {
    slug:'swing-score', cat:{label:'Lesson', cls:'lesson'}, icon:'🎯', sample:false,
    author:'GJ Singh', date:'Sep 5, 2026', read:'4 min read',
    title:'Why a high Swing Score can be a warning',
    excerpt:'The Swing Score is a machine-learning conviction reading — but higher is not always better. A low score can be the entry; a high one, on an extended name, can be the trap.',
    body:`<p>Every name on the board carries a single number — its <strong>Swing Score</strong>. It's the closest thing we have to a one-glance conviction reading, and it's easy to misread, so here is how we actually think about it.</p>
    <h2>Where the number comes from</h2>
    <p>The Swing Score is produced by a <strong>machine-learning model trained on years of U.S. market data</strong>. In plain terms, it measures how closely a stock's current behavior resembles the conditions that have historically preceded strong swing moves — a higher score means a stronger match to that profile. We keep the ingredients proprietary, but the output is deliberately simple: one number you can rank and compare across tonight's list.</p>
    <h2>How we use it — and how we don't</h2>
    <p>The score is a way to <strong>prioritize attention, not a buy button</strong>. It tells you which names most resemble the pattern right now, so you know where to look first. It does not tell you to act — and, the part most people miss, a higher number is not automatically a better trade.</p>
    <h2>Why a lower score can be the better entry</h2>
    <p>Our whole approach is to be interested in a quality name <em>while it is still out of favor and just beginning to steady</em> — not after it has already run. At that early stage, before the move is obvious, the score is often moderate rather than sky-high. That is frequently the best moment to be paying attention: you're early, the name is still near where it based, and the risk is easier to define. A calm, middling score on a fresh setup is not a weakness — it is often the opportunity.</p>
    <h2>Why a high score can become a barrier</h2>
    <p>Here is the counterintuitive part. A score tends to <em>climb as a move matures</em> — the more a stock has already done, the more it looks like a winner in progress, and the higher it reads. But by the time the number is very high, much of the move may already be behind it. On a name that has <strong>already extended</strong> well past where the setup first appeared, a high score is less a green light than a caution: it is telling you the move has largely happened, and chasing an extended name is a different — and usually worse — trade than being early near the line.</p>
    <p>That is exactly why the board splits names into <strong>Active</strong> (still near the setup, where the score is most useful) and <strong>Out of Range</strong> (already ran, shown for the record — not to chase). The score is one input; always read it together with where price sits, never on its own.</p>
    <h2>The takeaway</h2>
    <p>Treat the Swing Score as a <strong>ranking, not a verdict</strong>. Highest is not the goal — the setup you want is a strong-enough score on a name that is <em>still near its setup</em>, in a supportive market. A modest score early can be an opportunity; a very high score late, on a stretched name, can be a trap. As always, this is educational context for your own judgment — not a recommendation, and not a promise about any outcome.</p>`
  },
  {
    slug:'why-winners-dip', cat:{label:'Lesson', cls:'lesson'}, icon:'🧭', sample:false,
    author:'GJ Singh', date:'Aug 12, 2026', read:'4 min read',
    title:'Why almost every winner dips first',
    excerpt:'Across the completed paper book, setups that eventually ran barely ever went straight up. The number, and what it should do to your nerves.',
    body:`<p>If you take one statistical idea from this journal, make it this one: <strong>almost nothing goes straight up.</strong> Across the completed paper book, only a literal handful of setups reached a meaningful gain without ever trading below the signal price first. The normal path to a good outcome runs <em>through</em> some red.</p>
    <p>But — and this is the encouraging half — the red is usually modest. Of the setups that reached +5% at their peak, about two-thirds got there having dipped less than 5% along the way, and roughly a fifth got there with barely a scratch. A small, tolerable dip on the way up is not a warning sign. It is the toll.</p>
    <blockquote>The setups don't ask you to be right immediately. They ask you to still be there when the move arrives.</blockquote>
    <h2>What that means for your nerves</h2>
    <p>This is really a psychology point wearing a statistics costume. If you expect a clean line up, the first ordinary dip feels like being wrong, and you bail — often days before the setup would have rewarded you. If you expect a dip, the same move feels like the toll you already agreed to pay, and you hold. The <a data-nav="track" style="color:var(--primary); font-weight:600">Track Record</a> shows the fuller picture; <a data-nav="psychology" style="color:var(--primary); font-weight:600">Trading Psychology</a> goes deeper on sizing calm and starting small.</p>
    <p>The point here is narrow: a dip is the rule, not the exception, and knowing that in advance is half the discipline. See Sandisk (<a class="tklink" data-post="hold-the-dip-sndk">SNDK</a>) for what holding one looks like, and Capri (<a class="tklink" data-post="earnings-risk-cpri">CPRI</a>) for the kind of dip that does <em>not</em> come back.</p>`
  }
];
