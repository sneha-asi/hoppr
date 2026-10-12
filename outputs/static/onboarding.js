'use strict';
// Optional education, never an account or permission gate.
const welcomeSlides = [
  {title:'Same arrival. Shared way home.',copy:'Choose your flight and drop-off area. Hoppr looks for travellers arriving near your time and heading nearby.',icon:'plane'},
  {title:'Your party, your preferences.',copy:'Pool to share a cab, or choose Private for your party. Add people, large bags, wait time and women-only preferences under More options.',icon:'car'},
  {title:'Review it. Book it. Keep that price.',copy:'Compare the group, fare and savings before booking. Your booked fare stays locked if a flight or pool changes. Wallet credit applies before your payment method.',icon:'lock'}
];
let welcomeIndex = 0;
function renderWelcome(){
  const slide=welcomeSlides[welcomeIndex];
  $('welcome-progress').textContent=`${welcomeIndex+1} of ${welcomeSlides.length}`;
  $('welcome-title').textContent=slide.title;
  $('welcome-copy').textContent=slide.copy;
  $('welcome-art').innerHTML=icon(slide.icon);
  $('welcome-back').hidden=welcomeIndex===0;
  $('welcome-next').textContent=welcomeIndex===2?'Find my airport ride':'Next';
}
function openWelcome(){welcomeIndex=0;renderWelcome();$('welcome-dialog').showModal();}
function finishWelcome(){storage.set('hoppr-intro-seen','1');$('welcome-dialog').close();}
$('welcome-next').addEventListener('click',()=>{if(welcomeIndex===2)finishWelcome();else{welcomeIndex++;renderWelcome();$('welcome-title').tabIndex=-1;$('welcome-title').focus();}});
$('welcome-back').addEventListener('click',()=>{welcomeIndex--;renderWelcome();});
$('welcome-skip').addEventListener('click',finishWelcome);
$('welcome-dialog').addEventListener('cancel',()=>storage.set('hoppr-intro-seen','1'));
document.querySelectorAll('.guide-open').forEach(b=>b.addEventListener('click',openWelcome));
const help=document.createElement('section');
help.className='ride-help';
help.innerHTML=`<h2>A little clarity before you land.</h2>
<button class="text-button guide-open">Replay the welcome guide →</button>
<details><summary>How do you choose my pool?</summary><p>Ready times must fit everyone's wait limit. Drop-offs must be within 12 km of every other member. This demo cab holds up to 4 people and 4 large bags. Women-only requests group only with women.</p></details>
<details><summary>What if my flight is delayed?</summary><p>When the feed reports an ETA change, affected queued rides are re-matched and a banner explains the update. A booked fare stays locked. Once dispatched, contact support to coordinate changes. Demo flights are not a verified live feed.</p></details>
<details><summary>Where do I meet the driver?</summary><p>Open Trips, then View ride to find your pickup pass. Confirm the terminal meeting point with your driver. Share the four-digit code at pickup. This demo does not provide a live map or a verified pickup bay.</p></details>
<details><summary>No pool, or changed plans?</summary><p>You can still review a capped solo option. Eligible cancellations before pickup return paid amounts to your wallet; unpaid cash is not refunded. Payment and refund entries here are simulations.</p></details>
<button class="text-button support-trigger">Ask for help →</button>`;
$('panel-profile').append(help);
help.querySelector('.guide-open').addEventListener('click',openWelcome);
if(!storage.get('hoppr-intro-seen')&&!state.matchID&&!tripIDs.length)openWelcome();
