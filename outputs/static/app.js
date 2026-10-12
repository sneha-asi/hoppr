'use strict';
const $ = id => document.getElementById(id);
const escapeHTML = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const rupees = n => new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(n || 0);
const clock = t => t ? new Date(t).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'numeric',minute:'2-digit',hour12:true}).toUpperCase() : '—';
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const dateLabel = t => new Date(t).toLocaleDateString('en-GB',{timeZone:'Asia/Kolkata',day:'numeric',month:'short'});
const storage = {get(k){try{return localStorage.getItem(k);}catch{return null;}},set(k,v){try{localStorage.setItem(k,v);}catch{/* Storage is optional. */}}};
let walletID = storage.get('hoppr-wallet') || 'web-'+crypto.randomUUID(); storage.set('hoppr-wallet',walletID);
let saved;try{saved=JSON.parse(storage.get('hoppr-ride') || 'null');}catch{saved=null;}
const state = {tab:'rider',flights:[],areas:[],allAreas:[],ride:null,wallet:0,flightID:saved?.flightID || '',matchID:saved?.matchID || '',loadID:0,seenNotification:0,polling:false,initialPool:saved?.initialPool || false};
let tripIDs,tripMeta;try{tripIDs=JSON.parse(storage.get('hoppr-trips') || '[]');if(!Array.isArray(tripIDs))tripIDs=[];tripMeta=JSON.parse(storage.get('hoppr-trip-meta') || '{}');}catch{tripIDs=[];tripMeta={};}
function rememberTrip(id){if(!tripIDs.includes(id)){tripIDs.unshift(id);storage.set('hoppr-trips',JSON.stringify(tripIDs.slice(0,50)));}tripMeta[id]={airport:$('airport').value,flightID:state.flightID};storage.set('hoppr-trip-meta',JSON.stringify(tripMeta));}
const defaultWomen=storage.get('hoppr-women')==='true';$('profile-women').checked=defaultWomen;$('women-only').checked=defaultWomen;if(defaultWomen)$('gender').value='woman';
if(saved?.airport) $('airport').value=saved.airport;
const areaName = id => [...state.areas,...state.allAreas].find(a=>a.id===id)?.name || id;
function notice(text){$('notice').textContent=text;$('notice').hidden=!text;}
function error(text){$('error').textContent=text;$('error').hidden=!text;}
async function api(path,body){
  const response=await fetch(path,{headers:body?{'Content-Type':'application/json'}:{},method:body?'POST':'GET',body:body?JSON.stringify(body):undefined});
  const data=await response.json();
  if(!response.ok){const e=new Error(typeof data.detail==='string'?data.detail:'Please check your options and try again.');e.status=response.status;throw e;}
  return data;
}
let pendingActions=0;
async function action(button,fn){if(button?.disabled)return;error('');if(button)button.disabled=true;pendingActions++;document.body.setAttribute('aria-busy','true');try{await fn();}catch(e){error(e.message);}finally{if(button)button.disabled=false;pendingActions--;document.body.setAttribute('aria-busy',String(pendingActions>0));}}
function persist(){storage.set('hoppr-ride',JSON.stringify({airport:$('airport').value,flightID:state.flightID,matchID:state.matchID,initialPool:state.initialPool}));}
function step(n,focus=true){document.querySelectorAll('.step-panel').forEach((p,i)=>p.hidden=i!==n-1);document.querySelectorAll('.steps li').forEach((li,i)=>{li.classList.toggle('current',i===n-1);if(i===n-1)li.setAttribute('aria-current','step');else li.removeAttribute('aria-current');});if(focus){const heading=$('step-'+n).querySelector('h2');if(heading){heading.tabIndex=-1;heading.focus();}}}
function theme(value){if(value==='system')delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=value;storage.set('hoppr-theme',value);}
$('theme').value=storage.get('hoppr-theme') || 'system';theme($('theme').value);
function flightDetail(){const f=state.flights.find(f=>f.id===$('flight').value);state.flightID=f?.id || '';if(f){$('flight-detail').innerHTML=`<div class="flight-ticket-top"><div>${icon('plane')} <strong>${escapeHTML(f.flight_no)}</strong></div><span class="${f.delay_min>0?'delay-chip':'on-time-chip'}">${/cancel/i.test(f.status)?'Cancelled':f.delay_min>0?'Delayed · '+f.delay_min+' min':'On time'}</span></div><div class="landing-times"><div><span>Scheduled landing</span><b>${clock(f.scheduled)}</b></div><div><span>Estimated landing</span><b>${clock(f.estimated)}</b></div></div><div class="flight-ticket-bottom"><span>${escapeHTML(f.terminal || 'Terminal to confirm')} · ${dateLabel(f.estimated)} · IST</span><span>${f.source==='demo'?'Demo snapshot':escapeHTML(f.source)}</span></div>`;}else $('flight-detail').textContent='Choose an arrival from the board.';persist();}
function destinationDetail(){const a=state.areas.find(a=>a.id===$('destination').value);$('destination-detail').textContent=a?`${a.road_km} km by road · about ${a.drive_min} min · day solo fare ${rupees(a.day_fare)}`:'';}
function renderArrivals(){
  $('board-airport').textContent=$('airport').value;
  const demo=state.flights.every(f=>f.source==='demo');
  $('feed-label').textContent=demo?'DEMO SNAPSHOT · '+(state.flights[0]?dateLabel(state.flights[0].scheduled):'no flights'):'PROVIDER FEED · '+[...new Set(state.flights.map(f=>f.source))].join(', ');
  $('source-pill').textContent=demo?'Demo snapshot':'Provider feed';$('source-pill').classList.toggle('provider',!demo);$('source-pill').title='Last checked '+clock(new Date().toISOString())+' IST';
  $('arrival-list').innerHTML=state.flights.length?state.flights.map(f=>`<button class="arrival-row ${f.id===state.flightID?'selected':''}" data-flight="${escapeHTML(f.id)}" aria-label="${escapeHTML(f.flight_no)}, lands ${clock(f.estimated)}, ${f.delay_min>0?f.delay_min+' minutes delayed':'on time'}"><span><strong>${escapeHTML(f.flight_no)}</strong><small>${escapeHTML(f.airline || '')} · ${escapeHTML(f.terminal || '—')}</small></span><span class="landing">${clock(f.estimated)}${f.delay_min>0?`<del>${clock(f.scheduled)}</del>`:''}</span><span class="status ${f.delay_min>0?'delay':'ontime'}">${/cancel/i.test(f.status)?'CANCELLED':f.delay_min>0?'+'+f.delay_min+' MIN':escapeHTML(f.status==='scheduled'?'ON TIME':f.status.toUpperCase())}</span></button>`).join(''):'<p class="empty">No arrivals in this window.</p>';
  $('board-updated').textContent=`Checked ${clock(new Date().toISOString())} IST · refreshes every 30 seconds`;
}
async function loadAirport(){
  const ticket=++state.loadID,airport=$('airport').value;
  $('flight').disabled=true;$('to-destination').disabled=true;
  const [flights,areas]=await Promise.all([api('/flights?airport='+airport),api('/destinations?airport='+airport)]);
  if(ticket!==state.loadID)return;
  state.flights=flights;state.areas=areas;
  $('flight').innerHTML=flights.map(f=>`<option value="${escapeHTML(f.id)}">${escapeHTML(f.flight_no)} · ${clock(f.estimated)} · ${escapeHTML(f.terminal || '—')}</option>`).join('');
  if(flights.some(f=>f.id===state.flightID))$('flight').value=state.flightID;
  $('destination').innerHTML=areas.map(a=>`<option value="${escapeHTML(a.id)}">${escapeHTML(a.name)}</option>`).join('');
  $('destination-search').value='';$('popular-destinations').innerHTML=[...areas].sort((a,b)=>b.popularity-a.popularity).slice(0,3).map(a=>`<button data-destination="${escapeHTML(a.id)}">${escapeHTML(a.name)}</button>`).join('');
  $('flight').disabled=!flights.length;$('to-destination').disabled=!flights.length;flightDetail();destinationDetail();renderArrivals();
}
async function wallet(){const w=await api('/wallet?wallet_id='+encodeURIComponent(walletID));state.wallet=w.balance;$('wallet-balance').textContent=rupees(w.balance);$('wallet-page-balance').textContent=rupees(w.balance);const ledger=w.transactions.map(t=>`<li><span>${escapeHTML(t.label)}<br><small>${dateLabel(t.created_at)}</small></span><strong>${t.amount>=0?'+':''}${rupees(t.amount)}</strong></li>`).join('');$('wallet-ledger').innerHTML=ledger;$('wallet-page-ledger').innerHTML=ledger;}
function paymentPreview(ride){const used=Math.min(state.wallet,ride.total_fare);return `<div class="payment-preview"><div><span>Wallet applied first</span><strong>−${rupees(used)}</strong></div><div><span>${escapeHTML($('payment-method').selectedOptions[0].textContent)}</span><strong>${rupees(ride.total_fare-used)}</strong></div><small>UPI and card payments are simulated in this demo.</small></div>`;}
function renderRide(){
  const r=state.ride;if(!r)return;
  if(r.status==='cancelled'){$('match-result').innerHTML='<p class="eyebrow">RIDE CANCELLED</p><h2>Back in your wallet.</h2><p>Your refund appears under More options → Wallet activity.</p>';return;}
  const mine=r.group.find(m=>m.id===r.match_id),destination=areaName(mine?.destination);
  const people=r.group.reduce((s,m)=>s+m.party,0);
  const head=`<div class="price-head"><div><p class="eyebrow">${r.ride_type==='private'?'YOUR PRIVATE CAB':r.option==='pool'?'YOUR SHARED RIDE':'YOUR SOLO BACKUP'}</p><h2>${r.price_locked?'Your fare. Locked.':r.option==='pool'?'Found your flight-mates.':r.ride_type==='private'?'A cab of your own.':'A ride, either way.'}</h2><div class="fare-big">${rupees(r.per_seat_fare)} <small>/ seat</small></div></div><span class="tag">${r.option==='pool'?people+' people':r.ride_type==='private'?'Private':'Solo option'}</span></div><div class="saving-strip"><span>Solo cab <s>${rupees(r.solo_fare)}</s></span><strong>Save ${rupees(r.savings)} · ${r.savings_percent}%</strong></div><p class="micro">Your party total: ${rupees(r.total_fare)} · ${mine?.party || 1} seat(s). ${!r.price_locked?'Price is guaranteed once booked.':'Your locked fare stays the same if the pool changes.'}</p>`;
  const bags=r.group.reduce((s,m)=>s+m.bags,0);
  const cab=`<div class="seat-cab" aria-label="${people} of 4 seats and ${bags} of 4 luggage spaces occupied"><div class="seats">${[0,1,2,3].map(i=>`<span class="seat ${i<people?'occupied':''}">${i<people?icon('user'):'—'}</span>`).join('')}</div><p class="cab-capacity">${people} of 4 seats · ${bags} of 4 large bags</p></div>`;
  const group=`<ul class="pool-list">${r.group.map((m,i)=>`<li><span class="rider-number">${String(i+1).padStart(2,'0')}</span><div><p>${m.id===r.match_id?'You':'Fellow traveller'} → ${escapeHTML(areaName(m.destination))}</p><small>${m.party} seat(s) · ${m.bags} large bag(s) · ready ${clock(m.ready_time)} IST · ${escapeHTML(m.status)}</small></div></li>`).join('')}</ul>`;
  let bottom;
  if(r.price_locked){
    bottom=`<article class="boarding-pass" aria-label="Your pickup boarding pass"><div class="boarding-top"><strong>HOPPR / PICKUP PASS</strong><span>${escapeHTML($('airport').value)} → HOME</span></div><p class="micro" style="color:inherit">SHOW THIS CODE TO YOUR DRIVER</p><div class="pickup-code" aria-label="Pickup code ${escapeHTML(r.pickup_code)}">${escapeHTML(r.pickup_code)}</div><div class="boarding-route">${escapeHTML(destination)}</div><p class="locked-strip">✓ ${rupees(r.total_fare)} locked · ${r.driver_status==='assigned'?'Driver assigned':'Waiting for an available driver'}</p></article><p class="micro">${r.payment?`Wallet ${rupees(r.payment.wallet_applied)} applied before ${escapeHTML(r.payment.method.toUpperCase())} ${rupees(r.payment.payment_amount)}${r.payment.method==='cash'?' due at pickup':' · demo payment'}.`:''} Pickup location: terminal meeting point to be confirmed with your driver.</p><details><summary>More options for this ride</summary>${state.initialPool&&r.option==='solo'?'<p class="micro">Your pool changed. Keep your guaranteed solo fare, or cancel before pickup for a wallet refund.</p>':''}<button id="cancel-ride" class="text-button cancel">Cancel ride & refund to wallet</button><button class="text-button support-trigger">Contact support ↗</button></details>`;
  }else bottom=paymentPreview(r)+`<button id="book-ride" class="primary">Book · lock ${rupees(r.total_fare)} ${icon('lock')}</button><p class="micro">${r.option==='solo'?`Capped at ${rupees(r.solo_price_cap)} per cab. You don’t have to wait for a pool.`:'Companions are provisional until they book. Your confirmed fare will stay fixed.'}</p>${r.option==='solo'&&r.ride_type!=='private'?'<button id="keep-looking" class="text-button">Keep looking while you wait</button>':''}`;
  $('match-result').innerHTML=head+cab+group+bottom;
}
async function refreshRide(){if(!state.matchID)return;const r=await api('/match/'+state.matchID);const changed=JSON.stringify(state.ride)!==JSON.stringify(r);state.ride=r;if(changed)renderRide();const notes=await api('/notifications?booking_id='+state.matchID);const latest=notes.at(-1);if(latest&&latest.id>state.seenNotification){state.seenNotification=latest.id;const f=state.flights.find(f=>f.id===latest.flight_id) || await api('/flights?airport='+$('airport').value).then(fs=>fs.find(f=>f.id===latest.flight_id));const subject=latest.flight_id===state.flightID?'Your flight':'A flight in your pool';notice(`${subject} now lands ${clock(f?.estimated)}, ${r.trip_state==='queued'?'we re-matched your pool':'coordinate the updated arrival with your driver'}${r.price_locked?' · your booked price is guaranteed.':'.'}`);}}
async function findMatch(){
  $('match-result').innerHTML='<p class="eyebrow">SHARE THE LAST LEG</p><h2>Finding your ride…</h2><div class="loading-ribbon" aria-hidden="true"></div><p class="micro">Checking seats, bags and flight-mates.</p>';step(3);
  let ride;try{ride=await api('/match',{flight_id:$('flight').value,destination:$('destination').value,bags:Number($('bags').value),party:Number($('party').value),max_wait:Number($('max-wait').value),women_only:$('women-only').checked,gender:$('gender').value,ride_type:document.querySelector('input[name="ride-type"]:checked').value});}catch(e){step(2,false);throw e;}
  state.ride=ride;state.matchID=ride.match_id;state.initialPool=ride.option==='pool';state.seenNotification=0;persist();renderRide();step(3);
}
async function confirmBook(){
  try{state.initialPool=state.ride.option==='pool';state.ride=await api('/book',{match_id:state.matchID,quote_version:state.ride.quote_version,wallet_id:walletID,payment_method:$('payment-method').value});rememberTrip(state.matchID);persist();await wallet();renderRide();if(navigator.vibrate&&!matchMedia('(prefers-reduced-motion: reduce)').matches)navigator.vibrate(25);notice('You’re booked. Your fare is guaranteed, even if your pool changes.');}
  catch(e){if(e.status===409){await refreshRide();notice('Your quote changed. Review the new price, then book again.');}else throw e;}
}
async function cancelRide(){if(!confirm('Cancel this ride? Eligible paid amounts will return to your wallet.'))return;const result=await api('/cancel',{booking_id:state.matchID,wallet_id:walletID,reason:state.initialPool&&state.ride.option==='solo'?'pool_fell_through':'changed_plans'});await wallet();await refreshRide();notice(`${rupees(result.wallet_refund)} refunded to your wallet. Unpaid cash is not refunded.`);}
async function driver(){
  const trips=await api('/driver/trip'+($('driver-filter').value?'?driver_id='+encodeURIComponent($('driver-filter').value.trim()):''));
  const next={queued:'en_route',en_route:'arrived',arrived:'picked_up',picked_up:'completed'};
  const label={en_route:'Head to pickup',arrived:'Mark arrived',picked_up:'Verify codes & start ride',completed:'Complete trip'};
  $('driver-trips').innerHTML=trips.length?trips.map(t=>`<article class="trip-card"><div class="state">${escapeHTML(t.state.replace('_',' '))} · ${escapeHTML(t.driver_id || 'Awaiting driver')}</div><h2>${escapeHTML(t.airport)} / ${escapeHTML(t.terminal || 'Terminal TBC')}</h2><p class="micro">${t.occupied_seats}/4 seats · ${t.large_bags}/4 bags · Ref ${escapeHTML(t.trip_id.slice(0,8))}</p><ul>${t.riders.map(r=>`<li><strong>${escapeHTML(areaName(r.destination))}</strong><br>${r.party} seat(s) · ${r.bags} bag(s) · ready ${clock(r.ready_time)} IST${t.state==='arrived'?`<label for="code-${escapeHTML(r.booking_id)}">Passenger’s pickup code</label><input id="code-${escapeHTML(r.booking_id)}" data-code="${escapeHTML(r.booking_id)}" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" placeholder="4-digit code" autocomplete="off">`:''}</li>`).join('')}</ul><button class="primary driver-next" data-trip="${escapeHTML(t.trip_id)}" data-next="${next[t.state]}">${label[next[t.state]] || 'Completed'} ↗</button></article>`).join(''):'<div class="empty"><h2>Clear for your next ride.</h2><p>Confirmed trips appear here after a rider books.</p></div>';
}
async function ops(){const o=await api('/ops/summary');const metrics=[[o.cabs_needed,'Cabs needed'],[o.fewer_cars_percent+'%','Fewer cars'],[rupees(o.rider_savings),'Rider savings'],[o.average_riders_per_cab,'People per cab']];$('ops-metrics').innerHTML=metrics.map(([v,label])=>`<div class="metric"><strong>${escapeHTML(v)}</strong><span>${label}</span></div>`).join('')+`<p class="micro" style="grid-column:1/-1;padding:12px 18px;margin:0">${o.active_cabs_needed} active cab(s) · ${o.awaiting_driver} awaiting driver</p>`;const max=Math.max(...o.history_14_days.map(d=>d.cabs_needed),1);$('history-chart').innerHTML=o.history_14_days.map(d=>`<div class="bar" style="height:${Math.round(d.cabs_needed/max*85)}%" role="img" aria-label="${escapeHTML(d.date)}: ${d.cabs_needed} cabs"><span>${d.cabs_needed}</span></div>`).join('');$('history-table').innerHTML=o.history_14_days.map(d=>`<tr><th scope="row">${escapeHTML(d.date)}</th><td>${d.cabs_needed}</td><td>${d.fewer_cars_percent}%</td><td>${rupees(d.rider_savings)}</td><td>${d.average_riders_per_cab}</td></tr>`).join('');}
async function tab(name){state.tab=name;document.querySelectorAll('[role=tab]').forEach(b=>{const selected=b.dataset.tab===name;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;});document.querySelectorAll('[role=tabpanel]').forEach(p=>p.hidden=p.id!=='panel-'+name);document.querySelectorAll('.rider-utility').forEach(p=>p.hidden=true);document.querySelector('.rider-nav').hidden=name!=='rider';document.querySelectorAll('[data-view]').forEach(b=>{if(b.dataset.view==='home')b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});if(name==='driver')await driver();if(name==='ops')await ops();}
async function trips(){
  if(!tripIDs.length){$('my-trips').innerHTML='<div class="empty"><h2>Your next story starts here.</h2><p>Book a ride and your pickup pass will appear here.</p><button class="primary" data-view="home">Find a ride '+icon('arrow')+'</button></div>';return;}
  const results=await Promise.all(tripIDs.map(async id=>{try{return await api('/match/'+id);}catch(e){if(e.status===404)return null;throw e;}}));
  $('my-trips').innerHTML=results.filter(Boolean).map(r=>`<article class="history-trip"><p class="eyebrow">${escapeHTML(r.status)}</p><h2>${r.group?escapeHTML(areaName(r.group.find(m=>m.id===r.match_id)?.destination)):'Cancelled ride'}</h2><div class="subtle-ribbon" aria-hidden="true"></div>${r.total_fare!==undefined?`<p class="micro">${rupees(r.total_fare)} guaranteed · saved ${rupees(r.savings)}</p>`:'<p class="micro">Eligible paid amounts were returned to your wallet.</p>'}<button class="text-button" data-trip-view="${escapeHTML(r.match_id)}">View ride ${icon('arrow')}</button></article>`).join('');
}
async function riderView(name){await tab('rider');if(name!=='home'){$('panel-rider').hidden=true;$('panel-'+name).hidden=false;state.tab=name;}document.querySelectorAll('[data-view]').forEach(b=>{if(b.dataset.view===name)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});if(name==='wallet')await wallet();if(name==='trips')await trips();const heading=$('panel-'+(name==='home'?'rider':name)).querySelector('h1');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:false});}}
$('airport').addEventListener('change',()=>action(null,async()=>{state.flightID='';await loadAirport();step(1,false);}));
$('flight').addEventListener('change',()=>{flightDetail();renderArrivals();});
$('destination').addEventListener('change',destinationDetail);
$('destination-search').addEventListener('input',()=>{const q=$('destination-search').value.trim().toLowerCase();const matches=state.areas.filter(a=>a.name.toLowerCase().includes(q));$('destination').innerHTML=matches.map(a=>`<option value="${escapeHTML(a.id)}">${escapeHTML(a.name)}</option>`).join('');$('find-match').disabled=!matches.length;destinationDetail();});
$('to-destination').addEventListener('click',()=>step(2));
$('find-match').addEventListener('click',e=>action(e.currentTarget,findMatch));
$('refresh-arrivals').addEventListener('click',e=>action(e.currentTarget,loadAirport));
$('refresh-driver').addEventListener('click',e=>action(e.currentTarget,driver));
$('driver-filter').addEventListener('change',()=>action(null,driver));
$('refresh-ops').addEventListener('click',e=>action(e.currentTarget,ops));
$('theme').addEventListener('change',()=>theme($('theme').value));
$('payment-method').addEventListener('change',renderRide);
$('women-only').addEventListener('change',()=>{if($('women-only').checked)$('gender').value='woman';});
$('gender').addEventListener('change',()=>{if($('gender').value!=='woman')$('women-only').checked=false;});
$('profile-women').addEventListener('change',()=>{const value=$('profile-women').checked;storage.set('hoppr-women',String(value));$('women-only').checked=value;if(value)$('gender').value='woman';notice('Your preference will apply to your next match.');});
$('start-again').addEventListener('click',()=>{state.matchID='';state.ride=null;state.initialPool=false;persist();notice('');step(1);});
document.addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.tab)action(b,()=>tab(b.dataset.tab));
  if(b.dataset.view)action(b,()=>riderView(b.dataset.view));
  if(b.dataset.destination){$('destination-search').value='';$('destination').innerHTML=state.areas.map(a=>`<option value="${escapeHTML(a.id)}">${escapeHTML(a.name)}</option>`).join('');$('destination').value=b.dataset.destination;$('find-match').disabled=false;destinationDetail();}
  if(b.dataset.tripView)action(b,async()=>{state.matchID=b.dataset.tripView;const meta=tripMeta[state.matchID];if(meta){$('airport').value=meta.airport;state.flightID=meta.flightID;await loadAirport();}await riderView('home');await refreshRide();persist();step(3);});
  if(b.dataset.back)step(Number(b.dataset.back));
  if(b.dataset.flight){$('flight').value=b.dataset.flight;flightDetail();renderArrivals();step(2);}
  if(b.id==='book-ride')action(b,confirmBook);
  if(b.id==='cancel-ride')action(b,cancelRide);
  if(b.id==='keep-looking')action(b,async()=>{await refreshRide();notice('We’ll keep checking as flight-mates join. Your solo option is still here.');});
  if(b.classList.contains('support-trigger'))$('support-dialog').showModal();
  if(b.classList.contains('driver-next'))action(b,async()=>{const codes={};b.closest('.trip-card').querySelectorAll('[data-code]').forEach(i=>codes[i.dataset.code]=i.value);await api('/driver/step',{trip_id:b.dataset.trip,step:b.dataset.next,pickup_codes:codes});await driver();});
});
document.querySelector('.tabs').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=[...document.querySelectorAll('[role=tab]')];let i=tabs.indexOf(document.activeElement);i=e.key==='Home'?0:e.key==='End'?2:(i+(e.key==='ArrowRight'?1:2))%3;tabs[i].focus();action(null,()=>tab(tabs[i].dataset.tab));});
$('support-open').addEventListener('click',()=>$('support-dialog').showModal());
$('support-close').addEventListener('click',()=>$('support-dialog').close());
$('support-form').addEventListener('submit',e=>{e.preventDefault();action(e.submitter,async()=>{const result=await api('/support',{wallet_id:walletID,booking_id:state.matchID || null,message:$('support-message').value});$('support-status').textContent='Saved. Reference '+result.ticket_id.slice(0,8)+'. Demo only; no agent is connected.';$('support-message').value='';});});
async function poll(){if(document.hidden||state.polling)return;state.polling=true;try{const selected=$('flight').value;const flights=await api('/flights?airport='+$('airport').value);state.flights=flights;renderArrivals();const f=flights.find(f=>f.id===selected);if(f){const option=[...$('flight').options].find(o=>o.value===selected);if(option)option.textContent=`${f.flight_no} · ${clock(f.estimated)} · ${f.terminal || '—'}`;flightDetail();}await refreshRide();if(state.tab==='ops')await ops();if(state.tab==='driver'&&!$('driver-trips').contains(document.activeElement))await driver();}catch(e){error('Could not refresh. '+e.message);}finally{state.polling=false;}}
async function init(){await Promise.all([loadAirport(),wallet(),Promise.all(['DEL','BOM','BLR'].map(a=>api('/destinations?airport='+a))).then(rows=>state.allAreas=rows.flat())]);if(state.matchID){try{await refreshRide();if(state.ride.price_locked&&state.ride.status!=='cancelled')rememberTrip(state.matchID);step(3,false);}catch(e){if(e.status===404){state.matchID='';persist();}else throw e;}}}
action(null,init);setInterval(poll,30000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});
