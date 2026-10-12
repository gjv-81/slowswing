// The Slow Swing — "My story" page. THIS FILE IS THE ONLY PLACE THE STORY LIVES.
// index.html loads it with <script src="story.js"> and renders it on the
// My story page (#story). Edit the text here; never touch index.html for it.
//
//   * title   — the page headline.
//   * byline  — who and when, shown under the headline.
//   * body    — HTML. Use <p>, <h3>, <blockquote>, <ul>/<li>, <b>, <i>, <a>.
//               Links to site pages: <a data-nav="board">…</a>,
//               <a data-nav="how" data-scroll="how-regime">…</a>, <a data-post="slug">…</a>.
//   * foot    — optional closing note (defaults to the standard not-advice line).
//   After editing, check it parses:  node -e "require('./site/story.js')"
const STORY = {
  title: 'Why I started The Slow Swing',
  byline: 'GJ Singh · physician, trader, founder',
  body: `
<p>You are reading research produced by a model, so it seems fair to tell you who is behind it and why it exists.</p>
<p>I am a physician. I have been in the stock market for about fifteen years, and for nearly all of that time I did it the way most people do: reading everything I could find, learning the indicators, studying options and the mathematics behind them, and assembling a method out of whatever the internet was willing to teach me.</p>
<h2>The problem was never interest. It was hours.</h2>
<p>My evenings went into screening charts, hunting for a setup worth acting on the next morning. Endless hours of it, after a full clinical day. That is the part nobody warns a working professional about. Not the difficulty of the ideas, which are learnable, but the sheer nightly time cost of finding the few situations worth your attention among thousands that are not.</p>
<p>And underneath the hours sat a problem I could feel but could not prove. My method was RSI, MACD, the Fisher Transform, Bollinger bands, VWAP, moving averages and plenty more besides, used alone and stacked on top of one another, trusted because a great many people online say they work. I had never seen evidence that any of it did. What I had was effort, and the quiet assumption that effort and edge are the same thing.</p>
<h2>What I wanted was simple, and I could not build it</h2>
<p>I wanted something that would do the screening while I slept, apply the same rules every single night without getting tired or hopeful, and hand me a short list in the morning. For years that stayed a wish. Building it was not something a doctor with a day job and a family was going to do alone.</p>
<h2>What changed</h2>
<p><span style="color:var(--primary);text-decoration:underline;text-decoration-color:var(--primary);text-underline-offset:3px;font-weight:600">AI is the reason this exists.</span> I want to be plain about that rather than coy. I could not have built the model, run the testing, stood up the nightly pipeline, or created this website without it. What I brought was the domain knowledge and fifteen years of knowing exactly which problem I wanted solved. AI closed the distance between having that problem and having a working system, and that distance used to be uncrossable for someone like me.</p>
<h2>The first thing it did was dismantle my own method</h2>
<p>Once I could test properly, across about a thousand stocks and ten years rather than the handful of charts I could eyeball in an evening, my own indicators did not survive the examination.</p>
<p>On the same universe and the same question, how often did the price reach +5% within four weeks: an RSI oversold reading got there about <b>62%</b> of the time. A MACD cross, <b>53%</b>. A Bollinger band touch, <b>57%</b>. A day chosen at random, <b>54%</b>.</p>
<p><span style="color:var(--down); font-weight:600">Read that MACD number against the random one again. The cross I had spent years refining did no better than picking a day out of a hat.</span> That was not a comfortable finding. It was fifteen years of evenings. But it is precisely why I trust what replaced it, and why I would rather publish an unflattering number than a confident one.</p>
<h2>What replaced it</h2>
<p><span style="color:var(--ink); font-weight:600; text-decoration:underline; text-decoration-color:var(--line2); text-underline-offset:4px">A model trained on ten years of daily data across roughly six hundred stocks, then validated on years it had never seen, then tested head to head against the screens people actually use.</span> On that same +5% question our setups reached it <b>71%</b> of the time. For +10%, <b>45%</b> against 24% for a random day and 31% for the best of the classic screens. And they fired about 3,900 times across the decade where the classic screens fired between nine and forty one thousand times, which means far fewer names to wade through for a better hit rate.</p>
<p>The full comparison is on the <a data-nav="home" style="color:var(--primary); font-weight:600; cursor:pointer">home page</a>, and how the model was built is on <a data-nav="how" style="color:var(--primary); font-weight:600; cursor:pointer">How it works</a>. Those are hypothetical peak figures, levels the price reached rather than returns anyone earned.</p>
<h2>What I will not claim</h2>
<p>No technique is perfect and none can be. Our setups fail, sometimes completely, and we write those up too: <a data-post="when-a-setup-fails-bx" style="color:var(--primary); font-weight:600; cursor:pointer">the one that never worked at all</a> is a recent one. The edge here is probability, not certainty.</p>
<p>Two limits worth stating plainly.</p>
<p><b>The first is about the comparison.</b> We tested our setups against the screens most people actually use, RSI oversold, MACD crosses and Bollinger bands, with a randomly chosen day as the control, all on the same thousand stocks over the same ten years. We came out ahead on the measure the board is built around. That is a fair test and I will stand behind it, but it is not the same as having beaten every screener that exists, and I am not going to pretend otherwise.</p>
<p><b>The second is about what the edge is actually made of</b>, and it matters more. Our advantage is in <i>how often the opportunity turns up</i>: how often a flagged name goes on to reach +5% or +10% at some point. That advantage disappears if you buy and then look away for a month. Measured that way, by whether a name simply happens to be higher on a fixed date four weeks later, every screen we tested landed near <b>55%</b>, ours included. A coin flip, and no better than the rest of them.</p>
<p>The gap between those two measures is the whole reason this is research rather than a signal service. The model can put a name in front of you when the move is more likely to be coming. Whether you are still holding when it arrives, and what you do about it, is the part no screen can do for you, and it is why <a data-post="exits-play-a-role" style="color:var(--primary); font-weight:600; cursor:pointer">the post on exits</a> is the one I would read first.</p>
<p>The live book is still being proven forward, in public, with the losers left in. That is what the <a data-nav="track" style="color:var(--primary); font-weight:600; cursor:pointer">Track Record</a> is, and it will keep being published whether it flatters us or not.</p>
<h2>Why I publish it at all</h2>
<p>Because it solved my problem, and the problem is not rare. I no longer spend my nights screening. The scan, the scoring and the fundamental check are done before I sit down, and I look at a short list instead of a thousand charts. The hours came back.</p>
<p>What I do with those names is still my own decision, and what you do with them is still entirely yours.</p>
<p>If you are a professional with limited evenings and more curiosity than time, this was built by somebody sitting in exactly that chair.</p>
`,
  foot: `Educational research, not advice. Figures cited are from a hypothetical, backtested and paper tracked record as of October 2026; they are levels a price reached, not returns anyone earned, and past behaviour does not guarantee anything about the future. The Slow Swing is not a broker-dealer or investment adviser.`,

};
