"use strict";

const $ = selector => document.querySelector(selector);
const labels = {needs_you:"Needs you",running:"Running",done:"Turn complete",unknown:"Unconfirmed",cancelled:"Interrupted",failed:"Needs attention"};
const systemCopy = {
  "任务摘录":"Task excerpt", "回复摘录":"Reply excerpt", "最新进展摘录":"Progress excerpt",
  "未命名对话":"Untitled conversation", "尚无文字回复":"No reply yet",
  "工具":"Tool", "[图片]":"[Image]",
  "本地记录没有可确认的运行状态":"No confirmed runtime status is available in the local record.",
  "已有新消息，尚未读到本轮开始事件":"New message received. Waiting for this turn to start.",
  "已有新消息，等待本轮状态事件":"New message received. Waiting for a confirmed turn status.",
  "已有用户消息，等待可确认的执行记录":"Message received. Waiting for recorded activity.",
  "最后记录是运行中，但近期没有新事件；无法确认是否仍在工作":"No recent activity. The last running status is unconfirmed.",
  "已读到本轮开始事件":"This turn has started.", "已读到本轮完成事件":"This turn has completed.",
  "本轮已中止":"This turn was interrupted.", "用户已中止本轮":"You interrupted this turn.",
  "最近记录显示 Agent 正在调用工具":"The latest activity is a tool call.",
  "已读到 Claude 本轮回复结束标记":"Claude has finished this turn.",
  "正在生成回复，尚未读到结束标记":"A reply is in progress. No completion recorded yet.",
  "工具执行结果已写入":"Tool result received", "工具已返回结果，清除对应的等待提示":"Tool result received · request resolved",
  "本轮停止通知":"Agent finished responding", "已中止":"Interrupted", "会话已关闭":"Conversation closed", "会话状态已更新":"Conversation updated",
  "正在压缩上下文":"Compacting context",
  "上下文压缩已完成":"Context compaction completed",
  "上下文压缩已完成，继续处理本轮":"Context compacted. Continuing this turn.",
  "上下文压缩长时间没有后续事件，请查看原应用":"No follow-up after context compaction. Check the agent app.",
  "已检测到审批或回答请求，请到原应用处理；处理后随工具结果更新":"Waiting for your approval or answer in the original app. Updates when the tool returns.",
  "之前收到过审批 / 回答请求，等待状态已过期，请查看原应用":"The previous request is stale. Check the original app for its current status.",
  "可以直接在卡片里回复；超时后转回原应用处理":"Answer right here on the card. If the timer runs out, the request moves back to the agent app.",
  "已在看板回复，等待 Agent 继续":"Answer sent. Waiting for the agent to continue.",
  "你在看板允许了本次请求":"You allowed this request on the board", "你在看板拒绝了本次请求":"You denied this request on the board",
  "你在看板中止了本轮":"You stopped this turn on the board",
  "看板未在时限内作答，已转回原应用处理":"No answer on the board in time · handed back to the agent app",
  "这个请求已经结束":"This request has already ended.", "这个请求已经回复过了":"This request was already answered.",
  "已超过看板作答时间，请到原应用处理":"Time's up for answering here. Please answer in the agent app.",
  "这个请求不支持该操作":"That action isn't available for this request.", "请先写下回复内容":"Write a reply first.",
  "上一条消息还在处理中":"Your previous message is still being processed.",
  "Agent 还在工作中，请等本轮结束，或在卡片里回复它的请求":"The agent is still working. Wait for this turn to finish, or answer its request.",
  "只接受来自本机看板页面的操作":"Only this board page can do that.",
  "这条消息已经送达，无法取消":"That message was already delivered."
};
function systemText(value) {
  const text=String(value||"");
  if(systemCopy[text]) return systemCopy[text];
  for(const [before,after] of [["调用工具 · ","Tool call · "],["发起审批：","Approval requested: "],["等待回答：","Waiting for an answer: "],["你在看板回复了：","You replied on the board: "]]) {
    if(text.startsWith(before)) return after+systemText(text.slice(before.length));
  }
  if(text.endsWith(" 请求权限审批")) return text.slice(0,-7)+" needs permission";
  if(text.endsWith(" 等待你回答")) return text.slice(0,-6)+" is waiting for your answer";
  if(text.endsWith(" 本地会话目录尚不存在")) return text.split(" ")[0]+": no local conversations found yet.";
  if(text.endsWith(" 会话目录暂时无法读取")) return text.split(" ")[0]+": local conversations are temporarily unavailable.";
  if(text.startsWith("有一份本地记录暂时无法解析：")) return "A local record could not be read: "+text.split("：").slice(1).join("：");
  return text;
}
const icons = {
  chevron:'<path d="m7 10 5 5 5-5"/>',
  detail:'<path d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4 3.5V16h0a2 2 0 0 1-2-2Z"/><path d="M9 9h6M9 12.5h4"/>',
  arrow:'<path d="M7 17 17 7M7 7h10v10"/>',
  clock:'<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
  check:'<circle cx="12" cy="12" r="8"/><path d="m8 12 3 3 5-6"/>',
  pause:'<circle cx="12" cy="12" r="8"/><path d="M10 9v6m4-6v6"/>',
  spark:'<path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3ZM20 2v4m-2-2h4"/>',
  inbox:'<path d="m4 5-2 9v5h20v-5l-2-9H4ZM2 14h6l2 3h4l2-3h6"/>',
  activity:'<path d="M3 12h4l3-7 4 14 3-7h4"/>',
  flow:'<circle cx="6" cy="6" r="2.2"/><circle cx="18" cy="12" r="2.2"/><circle cx="6" cy="18" r="2.2"/><path d="M8 6h3a4 4 0 0 1 4 4v0M8 18h3a4 4 0 0 0 4-4v0"/>',
  pin:'<path d="M9 4h6l-1 5 3 3v2H7v-2l3-3-1-5ZM12 14v6"/>',
  close:'<path d="m7 7 10 10M17 7 7 17"/>',
  folder:'<path d="M3.5 7.5A2 2 0 0 1 5.5 5.5h3.6l2 2h7.4a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z"/>'
};
function el(tag,text="",className="") { const node=document.createElement(tag); node.textContent=text; node.className=className; return node; }
function icon(name,className="") {
  const node=document.createElementNS("http://www.w3.org/2000/svg","svg");
  node.setAttribute("viewBox","0 0 24 24"); node.setAttribute("aria-hidden","true");
  if(className)node.setAttribute("class",className);
  node.innerHTML=icons[name]||icons.activity; // Only static, application-owned SVG paths.
  return node;
}
let snapshot={conversations:[],sources:[],warnings:[],listeners:[],focus:[],settings:null};
let source="all",query="",project="",selected=null,lastDetail="",syncing=false,returnFocus=null,stickToBottom=true;
const summaryVisible=new Map(), expanded=new Set(), progressCache=new Map(), progressRequests=new Set();
const flowOpen=new Set(), flowCache=new Map(), drafts=new Map(), answering=new Set();
const projectOpen=new Set();
let momentsOpen=false,momentType="all",momentQuery="",momentEntries=[],activeMoment=null,fullHistory=false,detailVersion=0;
const emptyCopy={
  needs_you:["All quiet over here","Confirmed approvals and questions will land here.","inbox"],
  running:["A little breathing room","Start work in your agent app. Its activity will appear here.","activity"],
  done:["Good things take a moment","Completed turns will be waiting here when you're ready.","check"]
};
function relative(value) {
  const timestamp=Date.parse(value); if(!Number.isFinite(timestamp))return "Time unavailable";
  const seconds=Math.max(0,Math.floor((Date.now()-timestamp)/1000));
  if(seconds<60)return "Just now";
  if(seconds<3600)return `${Math.floor(seconds/60)}m ago`;
  if(seconds<86400)return `${Math.floor(seconds/3600)}h ago`;
  return `${Math.floor(seconds/86400)}d ago`;
}
function date(value) { return value?new Date(value).toLocaleString("en-GB"):"Time unavailable"; }
function clock(value) { return value?new Date(value).toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit",second:"2-digit"}):"—"; }
function shortTime(value) {
  if(!value)return "";
  const when=new Date(value),today=new Date().toDateString()===when.toDateString();
  return today?when.toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit"}):when.toLocaleString("en-GB",{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});
}
function duration(card) {
  if(!card.started_at||(!card.finished_at&&!["running","needs_you"].includes(card.status)))return "—";
  const seconds=Math.max(0,Math.floor(((card.finished_at?Date.parse(card.finished_at):Date.now())-Date.parse(card.started_at))/1000));
  if(!Number.isFinite(seconds))return "—";
  return seconds>=3600?`${Math.floor(seconds/3600)}h ${Math.floor(seconds%3600/60)}m`:`${Math.floor(seconds/60)}m ${seconds%60}s`;
}
function projectName(path) { return (path||"").split(/[\\/]/).filter(Boolean).pop()||"No project"; }
// Keep conversations from these legacy folders in the always-visible Other list.
const otherProjectNames=new Set(["wo","wosh"]);
function isOtherProject(path) { return !path||otherProjectNames.has(projectName(path)); }
function agentName(sourceName) { return sourceName==="Claude"?"Claude Code":sourceName; }
function statusLabel(card) { return card.status==="running"&&card.activity_phase==="compacting"?"Compacting context":labels[card.status]||card.status; }
async function api(path,options={}) {
  const acting=options.method&&options.method!=="GET";
  const headers={...(options.headers||{}),...(acting?{"X-PigentHub":"1"}:{}),...(options.body?{"Content-Type":"application/json"}:{})};
  const response=await fetch(path,{cache:"no-store",...options,headers});
  if(!response.ok) {
    let detail="";try{detail=(await response.json()).detail;}catch{}
    if(typeof detail==="string"&&detail)throw new Error(systemText(detail));
    throw new Error(response.status===404?"This conversation is temporarily unavailable.":response.status===409?"This reply or status has changed. Sync and try again.":"Couldn't read your workspace. Please try again.");
  }
  return response.json();
}
function cardElement(id) { return Array.from(document.querySelectorAll(".card")).find(node=>node.dataset.id===id); }
function focusCard(id,action="toggle") {
  const card=cardElement(id); const node=card&&Array.from(card.querySelectorAll("[data-action]")).find(n=>n.dataset.action===action);
  node?.focus({preventScroll:true});
}

/* ---------- markdown & math, rendered like the agent apps ---------- */
const MATH_TOKEN="PIGENTMATHTOKEN";
function protectMath(text,store) {
  // Pull math out before markdown runs, so "_" and "\" inside formulas survive. Code stays untouched.
  let out="",i=0;
  const keep=(tex,display)=>{store.push({tex,display});return MATH_TOKEN+(store.length-1)+"X";};
  while(i<text.length) {
    if(text.startsWith("```",i)||text.startsWith("~~~",i)) {
      const fence=text.slice(i,i+3),end=text.indexOf(fence,i+3),stop=end<0?text.length:end+3;
      out+=text.slice(i,stop);i=stop;continue;
    }
    if(text[i]==="`") {
      const end=text.indexOf("`",i+1);
      if(end>0){out+=text.slice(i,end+1);i=end+1;continue;}
    }
    if(text.startsWith("$$",i)) {
      const end=text.indexOf("$$",i+2);
      if(end>i+2){out+="\n\n"+keep(text.slice(i+2,end),true)+"\n\n";i=end+2;continue;}
    }
    if(text.startsWith("\\[",i)) {
      const end=text.indexOf("\\]",i+2);
      if(end>i+2){out+="\n\n"+keep(text.slice(i+2,end),true)+"\n\n";i=end+2;continue;}
    }
    if(text.startsWith("\\(",i)) {
      const end=text.indexOf("\\)",i+2);
      if(end>i+2){out+=keep(text.slice(i+2,end),false);i=end+2;continue;}
    }
    if(text[i]==="$"&&text[i-1]!=="\\") {
      // Inline $x$: no space just inside, no line break, and not a price like "$5 and $10".
      const match=/^\$([^\s$](?:[^$\n]*?[^\s$\\])?)\$(?!\d)/.exec(text.slice(i));
      if(match&&!/^\d+([.,]\d+)?$/.test(match[1])){out+=keep(match[1],false);i+=match[0].length;continue;}
    }
    out+=text[i];i+=1;
  }
  return out;
}
let markdownReady=false;
function setupMarkdown() {
  if(markdownReady||!window.marked||!window.DOMPurify)return markdownReady;
  marked.use({gfm:true,breaks:false,renderer:{image(href,title,text){return `<span class="md-image">[Image${text?": "+escapeHtml(text):""}]</span>`;}}});
  DOMPurify.addHook("afterSanitizeAttributes",node=>{if(node.tagName==="A"){node.setAttribute("target","_blank");node.setAttribute("rel","noopener noreferrer");}});
  markdownReady=true;return true;
}
function escapeHtml(text) { return String(text).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]); }
function renderMath(tex,display) {
  if(!window.katex)return escapeHtml(display?`$$${tex}$$`:`$${tex}$`);
  try { return katex.renderToString(tex.trim(),{displayMode:display,throwOnError:false,output:"html",strict:"ignore"}); }
  catch { return escapeHtml(tex); }
}
function markdownNode(text,className="md") {
  const node=el("div","",className);
  if(!setupMarkdown()){node.textContent=text;node.classList.add("plain");return node;}
  const math=[],html=marked.parse(protectMath(String(text||""),math));
  const clean=DOMPurify.sanitize(html,{FORBID_TAGS:["img","style","form","input","button","textarea","select","iframe"],FORBID_ATTR:["style"]});
  // KaTeX output is generated locally from the formula text, after sanitizing the rest.
  node.innerHTML=clean.replace(new RegExp(MATH_TOKEN+"(\\d+)X","g"),(_,n)=>{const item=math[Number(n)];return item?(item.display?`<div class="math-block">${renderMath(item.tex,true)}</div>`:renderMath(item.tex,false)):"";});
  for(const p of node.querySelectorAll("p"))if(p.children.length===1&&p.firstElementChild.classList.contains("math-block")&&p.textContent.trim()===p.firstElementChild.textContent.trim())p.replaceWith(p.firstElementChild);
  return node;
}

/* ---------- answering a request from the board ---------- */
function remaining(until) {
  const seconds=Math.max(0,Math.floor(until-Date.now()/1000));
  return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,"0")}`;
}
async function sendAnswer(card,request,action,box) {
  const text=drafts.get(request.request_id)||"";
  if(action==="reply"&&!text.trim()){box.querySelector("textarea")?.focus();box.querySelector(".answer-error").textContent="Write a reply first, then send it.";return;}
  if(action==="stop"&&!confirm("Stop this turn? The agent will end its current work."))return;
  answering.add(request.request_id);for(const b of box.querySelectorAll("button"))b.disabled=true;
  try {
    await api("/api/conversations/"+encodeURIComponent(card.id)+"/respond",{method:"POST",body:JSON.stringify({request_id:request.request_id,action,message:text})});
    drafts.delete(request.request_id);await sync();
  } catch(error) {box.querySelector(".answer-error").textContent=error.message;for(const b of box.querySelectorAll("button"))b.disabled=false;}
  finally {answering.delete(request.request_id);}
}
function answerBox(card,request,where) {
  const box=el("div","","answer"+(request.kind==="question"?" question":""));
  box.onclick=event=>event.stopPropagation();
  const head=el("div","","answer-head");
  head.append(el("strong",request.kind==="question"?"Question for you":"Permission request"));
  if(request.answerable){const timer=el("span","","answer-timer");timer.dataset.until=request.answer_until;timer.textContent=remaining(request.answer_until);timer.title="Answer here before the timer ends. After that, answer in the agent app.";head.append(timer);}
  box.append(head,el("p",systemText(request.reason),"answer-reason"));
  if(request.answered){box.append(el("p","Answer sent · waiting for the agent to continue…","answer-note"));return box;}
  if(!request.answerable){
    box.append(el("p",request.handed_back?"Not answered here in time, so it's back in the agent app.":"This request can only be answered in the agent app.","answer-note"));
    if(card.open_url)box.append(nativeLink(card));
    return box;
  }
  const area=el("textarea","","answer-text");area.rows=2;area.dataset.id=card.id;area.dataset.action="answer-"+where;
  area.placeholder=request.kind==="question"?"Type your answer…":"Optional: tell the agent what to do instead…";
  area.value=drafts.get(request.request_id)||"";area.setAttribute("aria-label",request.kind==="question"?"Your answer":"Reply to the agent");
  area.oninput=()=>drafts.set(request.request_id,area.value);
  area.onkeydown=event=>{if(event.key==="Enter"&&(event.metaKey||event.ctrlKey)&&!event.isComposing){event.preventDefault();sendAnswer(card,request,request.kind==="question"||area.value.trim()?"reply":"allow",box);}};
  const buttons=el("div","","answer-actions");
  const add=(action,label,kind,title)=>{const b=el("button",label,"answer-button "+kind);b.type="button";b.title=title;b.onclick=()=>sendAnswer(card,request,action,box);buttons.append(b);};
  if(request.kind==="question") add("reply","Send answer","primary","Send your answer and let the agent continue");
  else {
    add("allow","Allow","primary","Allow this once and let the agent continue");
    add("reply","Reply","secondary","Don't allow; send your note so the agent can adjust and continue");
    add("deny","Deny","secondary","Don't allow; the agent continues without it");
  }
  add("stop","Stop","danger","Stop this turn");
  box.append(area,buttons,el("p","","answer-error"));
  return box;
}

/* ---------- cards ---------- */
function nativeLink(card) {
  const name=agentName(card.source);
  const link=el("a",`Open in ${name}`,"open-native"); link.append(icon("arrow"));
  link.href=card.open_url; link.dataset.id=card.id; link.dataset.action="native";
  link.setAttribute("aria-label",`Open in ${name}: ${card.title}`);
  link.title=`Open this conversation in ${name}`;
  link.onclick=event=>event.stopPropagation();
  return link;
}
function summaryButton(card) {
  if(!card.summary_key||["short","waiting"].includes(card.summary_state))return null;
  const button=el("button","","summary-action"); button.type="button"; button.dataset.id=card.id; button.dataset.action="summary";
  const ready=card.summary_state==="ready", visible=summaryVisible.get(card.id)===card.summary_key;
  const retry=card.summary_state==="error";
  const label=ready?(visible?"Show excerpt":"View summary · cached"):retry?"Retry summary · uses quota":"Summarize · uses quota";
  button.append(icon("spark"),document.createTextNode(label));
  if(["queued","generating"].includes(card.summary_state)) { button.textContent="Summarizing…";button.disabled=true;return button; }
  button.title=ready?"Show a previously generated summary. No additional usage.":"Send this reply to Claude for a summary. Uses your Claude quota.";
  button.onclick=async event=>{
    event.stopPropagation();
    if(ready) { if(visible)summaryVisible.delete(card.id);else summaryVisible.set(card.id,card.summary_key);lastDetail="";render();await refreshDetail();return; }
    button.disabled=true;button.textContent="Requesting summary…";
    try {
      await api("/api/conversations/"+encodeURIComponent(card.id)+"/summary",{method:"POST",body:JSON.stringify({reply_key:card.summary_key,retry})});
      summaryVisible.set(card.id,card.summary_key);lastDetail="";await sync();
    } catch(error) { $("#notice").textContent=error.message;button.disabled=false;button.textContent=label; }
  };
  return button;
}
function sendNote(card) {
  if(!card.send)return null;
  if(card.send.state==="sending")return el("span","Sending your message…","send-note");
  if(card.send.state==="error")return el("span","Message failed: "+card.send.error,"send-note error");
  return null;
}
function cardNode(card) {
  const node=el("article","","card");node.dataset.id=card.id;node.dataset.expanded=String(expanded.has(card.id));node.dataset.selected=String(selected===card.id);
  node.draggable=true;
  node.ondragstart=event=>{event.dataTransfer.setData("application/x-pigent-conversation",card.id);event.dataTransfer.setData("text/plain",systemText(card.title));event.dataTransfer.effectAllowed="copy";document.body.classList.add("dragging");};
  node.ondragend=()=>document.body.classList.remove("dragging");
  const toggle=el("button","","card-toggle");toggle.type="button";toggle.dataset.id=card.id;toggle.dataset.action="toggle";
  toggle.setAttribute("aria-label",`Toggle progress: ${systemText(card.title)}`);
  toggle.setAttribute("aria-expanded",String(expanded.has(card.id)));
  const panelId="progress-"+encodeURIComponent(card.id);toggle.setAttribute("aria-controls",panelId);
  const top=el("span","","card-top");
  const badge=el("span",agentName(card.source),"agent "+card.source.toLowerCase());
  const projectLabel=el("span",projectName(card.project),"project");projectLabel.title=card.project;
  top.append(badge,projectLabel,icon("chevron","expand-chevron"));
  const showSummary=summaryVisible.get(card.id)===card.summary_key&&card.summary_state==="ready";
  toggle.append(top,el("strong",systemText(card.title),"card-title"));
  const requests=card.pending_requests||[];
  toggle.append(el("span",showSummary?card.summary:systemText(card.preview),"preview"+(showSummary?" summary":"")),el("span",showSummary?"AI summary · cached":systemText(card.preview_kind),"preview-tag"));
  const foot=el("span","","card-foot"), status=el("span","","status "+card.status);
  status.append(icon(card.status==="done"?"check":card.status==="needs_you"?"pause":"clock"),document.createTextNode(`${statusLabel(card)} · ${duration(card)}`));
  status.title=systemText(card.status_reason);
  const updated=el("span",relative(card.updated_at));updated.title=date(card.updated_at);foot.append(status,updated);toggle.append(foot);
  toggle.onclick=event=>{event.stopPropagation();toggleProgress(card.id);};node.append(toggle);
  for(const request of requests) {
    const box=answerBox(card,request,"card");
    // Selecting text inside the answer box must not start dragging the card.
    box.addEventListener("pointerdown",()=>{node.draggable=false;});
    box.addEventListener("pointerup",()=>{node.draggable=true;});
    box.addEventListener("pointerleave",()=>{node.draggable=true;});
    node.append(box);
  }
  const note=sendNote(card);if(note)node.append(note);
  const actions=el("div","","card-actions"), left=el("div","","card-actions-left");
  if(card.open_url)left.append(nativeLink(card));
  const summary=summaryButton(card);if(summary)left.append(summary);
  const pin=el("button","","icon-button pin-button");pin.type="button";pin.dataset.id=card.id;pin.dataset.action="pin";
  const pinned=snapshot.focus.includes(card.id);
  pin.title=pinned?"Remove from Focus":"Add to Focus";pin.setAttribute("aria-label",`${pin.title}: ${systemText(card.title)}`);pin.setAttribute("aria-pressed",String(pinned));
  pin.append(icon("pin"));pin.onclick=event=>{event.stopPropagation();pinned?unfocusConversation(card.id):focusConversation(card.id);};
  const details=el("button","","icon-button detail-open");details.type="button";details.dataset.id=card.id;details.dataset.action="details";
  details.title="Open conversation";details.setAttribute("aria-label",`Open conversation: ${systemText(card.title)}`);details.setAttribute("aria-haspopup","dialog");
  details.append(icon("detail"));details.onclick=event=>{event.stopPropagation();openDetail(card.id,details);};
  actions.append(left,pin,details);node.append(actions);
  const wrap=el("div","","progress-wrap"), clip=el("div","","progress-clip"), panel=el("section","","progress-panel");
  panel.id=panelId;panel.setAttribute("aria-label",`Latest progress: ${systemText(card.title)}`);
  wrap.setAttribute("aria-hidden",String(!expanded.has(card.id)));wrap.inert=!expanded.has(card.id);
  fillProgress(panel,card.id);clip.append(panel);wrap.append(clip);node.append(wrap);
  node.onclick=event=>{if(event.target.closest("button,a,textarea,.progress-panel,.answer")||window.getSelection()?.toString())return;toggleProgress(card.id);};
  return node;
}
function toggleProgress(id) {
  const opening=!expanded.has(id);if(opening)expanded.add(id);else expanded.delete(id);
  const node=cardElement(id);if(!node)return;
  node.dataset.expanded=String(opening);node.querySelector(".card-toggle").setAttribute("aria-expanded",String(opening));
  const wrap=node.querySelector(".progress-wrap");wrap.inert=!opening;wrap.setAttribute("aria-hidden",String(!opening));
  if(opening)loadProgress(id);
}
function timelineNode(events,className="timeline") {
  const timeline=el("ol","",className);
  for(const event of events) {
    const item=el("li"),time=el("time",clock(event.timestamp));time.title=date(event.timestamp);if(event.timestamp)time.dateTime=event.timestamp;
    item.append(el("span","","step-dot"),el("span",systemText(event.message),"step-message"),time);timeline.append(item);
  }
  return timeline;
}
function fillProgress(panel,id) {
  const saved=progressCache.get(id),data=saved?.data;
  const heading=el("h4","LATEST PROGRESS","progress-heading");heading.append(el("span","Auto-updating"));
  const parts=[heading];
  if(saved?.error) {
    parts.push(el("p",data?"Couldn't refresh. Showing the last recorded progress.":"Couldn't load progress. Please try again.","progress-error"));
    const retry=el("button","Try again","progress-retry");retry.onclick=()=>loadProgress(id);parts.push(retry);
  }
  if(data) {
    parts.push(el("p",systemText(data.status_reason)||labels[data.status],"progress-state"));
    if(data.events.length)parts.push(timelineNode(data.events));
    else parts.push(el("p","No steps recorded for this turn yet.","hint"));
    if(data.latest_update) {
      const update=el("div","","progress-update");update.append(el("strong","Latest agent update"),el("p",data.latest_update.text));parts.push(update);
    }
  } else if(!saved?.error)parts.push(el("p","Gathering the latest steps…","hint"));
  const open=flowOpen.has(id),flowButton=el("button","","flow-toggle");flowButton.type="button";flowButton.dataset.id=id;flowButton.dataset.action="flow";
  flowButton.setAttribute("aria-expanded",String(open));flowButton.append(icon("flow"),document.createTextNode(open?"Hide full workflow":"Full workflow"));
  flowButton.onclick=event=>{event.stopPropagation();toggleFlow(id);};
  parts.push(flowButton);
  if(open) {
    const flow=flowCache.get(id),box=el("div","","flow-box");
    if(!flow)box.append(el("p","Loading every step…","hint"));
    else if(flow.error)box.append(el("p","Couldn't load the workflow. Try again in a moment.","progress-error"));
    else if(!flow.events.length)box.append(el("p","No workflow steps recorded yet.","hint"));
    else {box.append(el("p",`${flow.events.length} steps · oldest first`,"flow-count"),timelineNode(flow.events,"timeline full"));}
    parts.push(box);
  }
  const scroll=panel.querySelector(".progress-update p")?.scrollTop||0,flowBox=panel.querySelector(".flow-box"),flowScroll=flowBox?.scrollTop,flowAtEnd=flowBox?flowBox.scrollHeight-flowBox.scrollTop-flowBox.clientHeight<30:true;
  panel.replaceChildren(...parts);const update=panel.querySelector(".progress-update p");if(update)update.scrollTop=scroll;
  const box=panel.querySelector(".flow-box");if(box)box.scrollTop=flowAtEnd?box.scrollHeight:flowScroll;
}
async function loadProgress(id) {
  if(!expanded.has(id)||progressRequests.has(id))return;
  progressRequests.add(id);
  try {
    const [data,flow]=await Promise.all([api("/api/conversations/"+encodeURIComponent(id)+"/progress"),flowOpen.has(id)?api("/api/conversations/"+encodeURIComponent(id)+"/workflow").catch(()=>({error:true})):null]);
    progressCache.set(id,{data});if(flow)flowCache.set(id,flow);
  }
  catch(error) { progressCache.set(id,{...progressCache.get(id),error:true}); }
  finally { progressRequests.delete(id);const panel=cardElement(id)?.querySelector(".progress-panel");if(panel)fillProgress(panel,id); }
}
function toggleFlow(id) {
  if(flowOpen.has(id))flowOpen.delete(id);else {flowOpen.add(id);flowCache.delete(id);}
  const panel=cardElement(id)?.querySelector(".progress-panel");if(panel)fillProgress(panel,id);
  if(flowOpen.has(id))loadProgress(id);
}

/* ---------- focus sidebar: single conversations, plus project filters ---------- */
async function saveFocus(ids) {
  const previous=snapshot.focus;snapshot.focus=ids;render();
  try {const result=await api("/api/focus",{method:"PUT",body:JSON.stringify({conversations:ids})});snapshot.focus=result.conversations;}
  catch(error) {snapshot.focus=previous;$("#notice").textContent=error.message;}
  render();
}
function focusConversation(id) { if(id&&!snapshot.focus.includes(id))saveFocus([...snapshot.focus,id]); }
function unfocusConversation(id) { saveFocus(snapshot.focus.filter(item=>item!==id)); }
function removeButton(label,onclick) {
  const button=el("button","","side-extra");button.type="button";button.append(icon("close"));
  button.title="Remove from Focus";button.setAttribute("aria-label",label);button.onclick=onclick;return button;
}
function focusItem(id) {
  const card=snapshot.conversations.find(c=>c.id===id),item=el("li","","side-row focus-row"+(selected===id?" active":""));
  if(!card) {
    item.append(el("span","Conversation no longer available","side-item side-missing"),removeButton("Remove unavailable conversation from Focus",()=>unfocusConversation(id)));
    return item;
  }
  const title=systemText(card.title),button=el("button","","side-item");button.type="button";button.title=`${title}\n${agentName(card.source)} · ${card.project||"No project"}`;
  const text=el("span","","side-text");text.append(el("span",title,"side-name"),el("span",`${agentName(card.source)} · ${projectName(card.project)}`,"side-sub"));
  button.append(el("i","","side-dot "+card.status),text);
  button.onclick=()=>openDetail(id,button);
  item.append(button,removeButton(`Remove ${title} from Focus`,()=>unfocusConversation(id)));
  return item;
}
function projectStats(path) {
  const cards=snapshot.conversations.filter(c=>c.project===path);
  return {total:cards.length,needs:cards.filter(c=>["needs_you","failed"].includes(c.status)).length,running:cards.filter(c=>c.status==="running").length};
}
function conversationItem(card) {
  const item=el("li","","side-row conversation-item"+(selected===card.id?" active":""));
  const button=el("button","","side-item");button.type="button";button.dataset.sideKey="chat:"+card.id;
  button.title=`${systemText(card.title)}\n${agentName(card.source)} · ${labels[card.status]||card.status}`;
  if(selected===card.id)button.setAttribute("aria-current","page");
  const text=el("span","","side-text");text.append(el("span",systemText(card.title),"side-name"),el("span",agentName(card.source),"side-sub"));
  button.append(el("i","","side-dot "+card.status),text);button.onclick=()=>openDetail(card.id,button);
  item.append(button);return item;
}
function projectItem(path,index) {
  const stats=projectStats(path),item=el("li","","project-branch"),row=el("div","","side-row"+(project===path?" active":""));
  const isOpen=projectOpen.has(path),button=el("button","","side-item project-folder");button.type="button";
  button.dataset.sideKey="folder:"+path;button.setAttribute("aria-expanded",String(isOpen));button.setAttribute("aria-controls","project-children-"+index);button.title=path;
  button.append(icon("chevron","folder-chevron"),icon("folder","side-icon"),el("span",projectName(path),"side-name"));
  const badges=el("span","","side-badges");
  if(stats.needs)badges.append(el("span",String(stats.needs),"side-badge needs"));
  if(stats.running)badges.append(el("span",String(stats.running),"side-badge running"));
  badges.append(el("span",String(stats.total),"side-count"));button.append(badges);
  button.onclick=()=>{
    if(projectOpen.has(path))projectOpen.delete(path);else projectOpen.add(path);
    project=path;if(selected)closeDetail();else render();
  };
  row.append(button);item.append(row);
  const children=el("ul","","side-list project-children");children.id="project-children-"+index;children.hidden=!isOpen;
  if(isOpen)children.append(...snapshot.conversations.filter(c=>c.project===path).map(conversationItem));
  item.append(children);return item;
}
function renderSidebar() {
  const focus=snapshot.focus||[],sideFocus=document.activeElement?.dataset?.sideKey;
  $("#all-projects").setAttribute("aria-pressed",String(!project));$("#all-projects").classList.toggle("active",!project);
  $("#all-count").textContent=snapshot.conversations.length;
  $("#focus-list").replaceChildren(...focus.map(focusItem));
  $("#focus-hint").textContent=focus.length?"Drop more cards here.":"Drag a card here to keep that conversation close at hand.";
  const latest=new Map();
  for(const c of snapshot.conversations)if(!isOtherProject(c.project)&&(!latest.has(c.project)||(c.updated_at||"")>latest.get(c.project)))latest.set(c.project,c.updated_at||"");
  const projects=[...latest.keys()].sort((a,b)=>latest.get(b).localeCompare(latest.get(a)));
  $("#recent-list").replaceChildren(...projects.map(projectItem));
  const loose=snapshot.conversations.filter(c=>isOtherProject(c.project));
  if(loose.length) {
    const group=el("li","","loose-group"),list=el("ul","","side-list");
    group.append(el("h3","Other","loose-heading"));list.append(...loose.map(conversationItem));group.append(list);$("#recent-list").append(group);
  }
  if(!projects.length&&!loose.length)$("#recent-list").append(el("li","No conversations yet.","side-empty"));
  if(sideFocus)Array.from(document.querySelectorAll("[data-side-key]")).find(n=>n.dataset.sideKey===sideFocus)?.focus({preventScroll:true});
  const select=$("#wait-select"),settings=snapshot.settings;
  if(settings&&document.activeElement!==select) {
    const choices=settings.wait_choices.map(s=>{const o=el("option",s<60?`${s} sec`:`${s/60} min`);o.value=s;return o;});
    select.replaceChildren(...choices);select.value=String(settings.approval_wait_seconds);
  }
  const needs=snapshot.conversations.filter(c=>c.status==="needs_you").length,running=snapshot.conversations.filter(c=>c.status==="running").length;
  const answering=(snapshot.listeners||[]).some(l=>l.answering);
  $("#side-state").replaceChildren(el("span",needs?`${needs} waiting for you`:"Nothing waiting for you",needs?"state-needs":""),document.createTextNode(` · ${running} running`),
    el("small",answering?"Board answers: on":"Board answers: install hooks to turn on"));
}
const focusZone=$("#focus-zone"),DRAG_TYPE="application/x-pigent-conversation";
focusZone.addEventListener("dragover",event=>{if(event.dataTransfer.types.includes(DRAG_TYPE)){event.preventDefault();event.dataTransfer.dropEffect="copy";focusZone.classList.add("drop-ready");}});
focusZone.addEventListener("dragleave",event=>{if(!focusZone.contains(event.relatedTarget))focusZone.classList.remove("drop-ready");});
focusZone.addEventListener("drop",event=>{event.preventDefault();focusZone.classList.remove("drop-ready");document.body.classList.remove("dragging");const id=event.dataTransfer.getData(DRAG_TYPE);if(id)focusConversation(id);});
$("#all-projects").onclick=()=>{project="";if(selected)closeDetail();else render();};
$("#wait-select").onchange=async event=>{
  try {const saved=await api("/api/settings",{method:"PUT",body:JSON.stringify({approval_wait_seconds:Number(event.target.value)})});snapshot.settings={...snapshot.settings,...saved};}
  catch(error) {$("#notice").textContent=error.message;}
};

/* ---------- board ---------- */
function render() {
  const active=document.activeElement, focusId=active?.closest(".card")?active.dataset.id:null, focusAction=active?.dataset?.action;
  const selection=active?.tagName==="TEXTAREA"&&focusId?[active.selectionStart,active.selectionEnd]:null;
  const cards=snapshot.conversations.filter(card=>(source==="all"||card.source===source)&&(!project||card.project===project)&&`${card.title} ${card.project} ${card.preview}`.toLowerCase().includes(query));
  for(const lane of ["needs_you","running","done","unknown"]) {
    const rows=cards.filter(card=>lane==="unknown"?["unknown","cancelled"].includes(card.status):lane==="needs_you"?["needs_you","failed"].includes(card.status):card.status===lane);
    const container=$("#"+lane),scroll=container.scrollTop;container.replaceChildren(...rows.map(cardNode));container.scrollTop=scroll;
    if(lane!=="unknown") {
      $("#count-"+lane).textContent=rows.length;
      if(!rows.length) { const [title,description,symbol]=emptyCopy[lane],empty=el("div","","empty"),art=el("span","","empty-icon");art.append(icon(symbol));empty.append(art,el("strong",title),el("p",description));container.append(empty); }
    } else {$("#unknown-count").textContent=rows.length;$("#unknown-section").hidden=!rows.length;}
  }
  if(focusId) {
    focusCard(focusId,focusAction);
    const again=document.activeElement;if(selection&&again?.tagName==="TEXTAREA")again.setSelectionRange(...selection);
  }
  $("#total").textContent=`${cards.length} of ${snapshot.conversations.length} local conversations`+(project?` · ${projectName(project)}`:"");
  for(const count of document.querySelectorAll("[data-filter-count]"))count.textContent=snapshot.conversations.filter(c=>count.dataset.filterCount==="all"||c.source===count.dataset.filterCount).length;
  $("#observer-status").textContent="Approval signals · "+(snapshot.listeners||[]).map(item=>`${item.source}: ${item.last_seen?"events received":item.configured?"configured, awaiting events":"setup needed"}`).join(" · ");
  const announcement=`${snapshot.conversations.filter(c=>c.status==="needs_you").length} conversations need you. ${snapshot.conversations.filter(c=>c.status==="running").length} running.`;
  if($("#board-announcement").textContent!==announcement)$("#board-announcement").textContent=announcement;
  renderSidebar();
}

/* ---------- conversation drawer: reads and replies like the agent app ---------- */
async function openDetail(id,node) {
  returnFocus=node;selected=id;lastDetail="";stickToBottom=true;fullHistory=false;detailVersion++;activeMoment=null;momentQuery="";$("#moments-search").value="";momentEntries=[];renderMoments();
  $("#details").hidden=false;document.body.style.overflow="hidden";$(".shell").inert=true;
  $("#detail-content").replaceChildren(el("p","Opening your conversation…","hint"));$("#chat-tools").replaceChildren();
  $("#composer-text").value=drafts.get("chat:"+id)||"";resizeComposer();
  const version=detailVersion;render();await refreshDetail();if(selected===id&&version===detailVersion)$("#composer-text").focus();
}
function closeDetail() {
  const id=selected;selected=null;detailData=null;lastDetail="";detailVersion++;$("#details").hidden=true;$("#backdrop").hidden=true;document.body.style.overflow="";$(".shell").inert=false;
  render();focusCard(id,"details");if(!cardElement(id))returnFocus?.focus();
}
function messageGroups(messages) {
  const groups=[];
  for(const message of messages) {
    const last=groups[groups.length-1];
    if(last&&last.role===message.role)last.items.push(message);else groups.push({role:message.role,items:[message]});
  }
  return groups;
}
let detailData=null;
function composerState(data) {
  const name=agentName(data.source);
  if(data.send?.state==="sending")return {locked:true,hint:`${name} is replying to your message…`};
  if(data.send?.state==="error")return {locked:false,hint:"Last message failed: "+data.send.error,error:true};
  if(["running","needs_you"].includes(data.status))
    return {locked:false,hint:`Queue for ${name} through its next Stop / prompt hook. Delivery depends on enabled hooks; the app may show it as hook context.`};
  return {locked:false,hint:`Continues this session using ${name} CLI · uses model quota. Desktop live sync is not confirmed; reload / resume there to check. Avoid sending from both at once.`};
}
function outboxNodes(data) {
  // Messages sent from the board while the agent worked. Skip ones the transcript already shows.
  const shown=data.messages.filter(m=>m.role==="user").map(m=>m.text);
  const nodes=[];
  for(const item of data.outbox||[]) {
    if(item.delivered&&shown.some(text=>text.includes(item.text.trim())))continue;
    const row=el("div","","chat-row user outbox"+(item.delivered?"":" queued")),bubble=el("div","","bubble");
    bubble.append(el("div",item.text,"user-text"));
    const meta=el("div",item.delivered?`You · handed to ${item.via||"agent"} hook ${shortTime(new Date(item.delivered*1000).toISOString())} · app display unconfirmed`:"You · queued for next Stop / prompt hook","chat-time");
    row.append(bubble,meta);
    if(!item.delivered) {
      const cancel=el("button","Cancel","outbox-cancel");cancel.type="button";
      cancel.onclick=async()=>{cancel.disabled=true;try{await api(`/api/conversations/${encodeURIComponent(data.id)}/outbox/${item.id}`,{method:"DELETE"});lastDetail="";await refreshDetail();}catch(error){composerNote(error.message,true);cancel.disabled=false;}};
      meta.append(cancel);
    }
    nodes.push(row);
  }
  return nodes;
}
async function refreshDetail() {
  const id=selected,version=detailVersion;if(!id)return;
  try {
    const data=await api("/api/conversations/"+encodeURIComponent(id)+(fullHistory?"?full=true":""));if(selected!==id||version!==detailVersion)return;
    detailData=data;
    const state=composerState(data);
    $("#composer-send").disabled=state.locked;$("#composer-text").disabled=state.locked;
    if(!$("#composer-hint").dataset.sticky){$("#composer-hint").textContent=state.hint;$("#composer-hint").classList.toggle("error",Boolean(state.error));}
    $("#composer-text").placeholder=`Message ${agentName(data.source)}…`;
    const signature=JSON.stringify(data);if(signature===lastDetail)return;lastDetail=signature;
    $("#drawer-heading").textContent=systemText(data.title);
    $("#chat-meta").replaceChildren(el("span",agentName(data.source),"agent "+data.source.toLowerCase()),el("span",projectName(data.project),"chat-project"),el("span",statusLabel(data),"chat-status "+data.status));
    $("#chat-meta").title=`${data.project||"No project"} · ${systemText(data.status_reason)}`;
    const tools=[];if(data.open_url)tools.push(nativeLink(data));const summary=summaryButton(data);if(summary)tools.push(summary);
    $("#chat-tools").replaceChildren(...tools);
    const root=$("#detail-content"),atBottom=root.scrollHeight-root.scrollTop-root.clientHeight<80,scroll=root.scrollTop;
    const parts=[];
    if(data.messages_omitted) {
      const earlier=el("button",`Load ${data.messages_omitted} earlier messages · local, 0 tokens`,"quiet load-earlier");earlier.type="button";
      earlier.onclick=async()=>{earlier.disabled=true;fullHistory=true;detailVersion++;lastDetail="";stickToBottom=false;await refreshDetail();root.scrollTop=0;};
      parts.push(earlier);
    }
    const entries=[];let messageIndex=data.messages_omitted||0;
    for(const group of messageGroups(data.messages)) {
      const row=el("div","","chat-row "+group.role),bubble=el("div","","bubble");
      for(const message of group.items) {
        const index=messageIndex++,content=group.role==="assistant"?markdownNode(message.text):el("div",message.text,"user-text");
        content.id="chat-message-"+index;content.tabIndex=-1;content.classList.add("message-anchor");
        const label=message.text.replace(/\s+/g," ").trim();
        if(group.role==="user")entries.push({id:content.id,type:"prompt",label,time:message.timestamp});
        else {
          const headings=Array.from(content.querySelectorAll("h1,h2,h3,h4,h5,h6"));
          if(message===group.items[group.items.length-1])entries.push({id:content.id,type:"reply",label,time:message.timestamp});
          headings.forEach((heading,n)=>{heading.id=content.id+"-heading-"+n;heading.tabIndex=-1;heading.classList.add("message-anchor");entries.push({id:heading.id,type:"heading",label:heading.textContent,time:message.timestamp});});
        }
        bubble.append(content);
      }
      const meta=el("div",`${group.role==="user"?"You":agentName(data.source)} · ${shortTime(group.items[group.items.length-1].timestamp)}`,"chat-time");
      meta.title=date(group.items[group.items.length-1].timestamp);
      row.append(bubble,meta);parts.push(row);
    }
    if(!data.messages.length)parts.push(el("p","No messages yet. New activity will appear automatically.","hint"));
    if(data.summary_state==="ready"&&summaryVisible.get(data.id)===data.summary_key) {
      const box=el("div","","summary-box");box.append(el("strong","AI summary of the latest reply · cached"),el("p",data.summary));parts.push(box);
    }
    parts.push(...outboxNodes(data));
    for(const request of data.pending_requests||[])parts.push(answerBox(data,request,"chat"));
    if(data.status==="running")parts.push(el("div",data.activity_phase==="compacting"?`${agentName(data.source)} is compacting context…`:`${agentName(data.source)} is working…`,"typing"));
    if(data.send?.state==="sending")parts.push(el("div","Sending your message…","typing"));
    if(document.activeElement?.dataset?.action==="answer-chat"){lastDetail="";return;}
    root.replaceChildren(...parts);momentEntries=entries;renderMoments();
    root.scrollTop=stickToBottom||atBottom?root.scrollHeight:scroll;stickToBottom=false;
  } catch(error) {if(selected===id)$("#detail-content").replaceChildren(el("p",error.message,"hint"));}
}
/* Local navigation only: derived from visible messages, never calls a model. */
function renderMoments() {
  $("#moments").hidden=!momentsOpen;$("#moments-toggle").setAttribute("aria-expanded",String(momentsOpen));
  $("#details").classList.toggle("has-moments",momentsOpen);
  const rows=momentEntries.filter(e=>(momentType==="all"||e.type===momentType)&&e.label.toLowerCase().includes(momentQuery));
  const scroll=$("#moments-list").scrollTop;
  $("#moments-count").textContent=`${rows.length} of ${momentEntries.length} moments`;
  $("#moments-list").replaceChildren(...rows.map(entry=>{
    const item=el("li"),button=el("button","","moment-link");button.type="button";
    button.title=entry.label;button.dataset.target=entry.id;
    if(activeMoment===entry.id)button.setAttribute("aria-current","location");
    button.append(el("span",({prompt:"Your prompt",heading:"Heading",reply:"Agent reply"})[entry.type]+" · "+shortTime(entry.time),"moment-meta"),el("span",entry.label.slice(0,200),"moment-label"));
    button.onclick=()=>jumpToMoment(entry.id);item.append(button);return item;
  }));
  if(!rows.length)$("#moments-list").append(el("li",momentEntries.length?"No matching moments.":"Moments will appear with your conversation.","side-empty"));
  $("#moments-list").scrollTop=scroll;
  for(const entry of momentEntries)document.getElementById(entry.id)?.classList.toggle("jump-target",entry.id===activeMoment);
}
function jumpToMoment(id) {
  const node=document.getElementById(id);if(!node)return;
  activeMoment=id;stickToBottom=false;renderMoments();
  const root=$("#detail-content");root.scrollTop+=node.getBoundingClientRect().top-root.getBoundingClientRect().top-24;
  node.focus({preventScroll:true});
}
$("#moments-toggle").onclick=()=>{momentsOpen=!momentsOpen;renderMoments();};
$("#moments-search").oninput=event=>{momentQuery=event.target.value.trim().toLowerCase();renderMoments();};
document.querySelectorAll("[data-moment-type]").forEach(button=>button.onclick=()=>{
  momentType=button.dataset.momentType;document.querySelectorAll("[data-moment-type]").forEach(b=>b.setAttribute("aria-pressed",String(b===button)));renderMoments();
});
$("#jump-latest").onclick=()=>{activeMoment=null;renderMoments();const root=$("#detail-content");root.scrollTop=root.scrollHeight;};
function resizeComposer() { const area=$("#composer-text");area.style.height="auto";area.style.height=Math.min(area.scrollHeight,200)+"px"; }
$("#composer-text").addEventListener("input",()=>{if(selected)drafts.set("chat:"+selected,$("#composer-text").value);resizeComposer();});
$("#composer-text").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey&&!event.isComposing){event.preventDefault();$("#composer").requestSubmit();}});
function composerNote(text,error=false) {
  const hint=$("#composer-hint");hint.textContent=text;hint.classList.toggle("error",error);hint.dataset.sticky="1";
  clearTimeout(composerNote.timer);composerNote.timer=setTimeout(()=>{delete hint.dataset.sticky;if(detailData)refreshDetail();},8000);
}
$("#composer").addEventListener("submit",async event=>{
  event.preventDefault();
  const id=selected,text=$("#composer-text").value.trim();if(!id||!text)return;
  $("#composer-send").disabled=true;
  try {
    const result=await api("/api/conversations/"+encodeURIComponent(id)+"/messages",{method:"POST",body:JSON.stringify({text})});
    drafts.delete("chat:"+id);
    if(selected===id) {
      $("#composer-text").value="";resizeComposer();stickToBottom=true;lastDetail="";
      composerNote(result.queued?"Queued for the next Stop / prompt hook. App display is not confirmed.":"Started a CLI continuation of this session. Check the app after reload / resume.");
    }
    await sync();
  } catch(error) {if(selected===id)composerNote(error.message,true);else $("#notice").textContent=error.message;}
  finally {if(selected===id)$("#composer-send").disabled=detailData?.id===id&&composerState(detailData).locked;}
});

async function sync() {
  if(syncing)return;syncing=true;$("#refresh").disabled=true;
  try {
    const next=await api("/api/conversations");snapshot={...next,focus:next.focus||[]};
    $("#connection").classList.remove("offline");$("#connection").textContent="Synced · "+clock(snapshot.scanned_at);
    $("#notice").textContent=snapshot.warnings.map(systemText).join(" ");
    // Rebuilding cards mid-typing would break IME input (e.g. Chinese); render once typing stops.
    if(typingInCard())renderPending=true;else render();
    const visible=new Set(Array.from(document.querySelectorAll(".card")).map(node=>node.dataset.id));
    await Promise.all([refreshDetail(),...Array.from(expanded).filter(id=>visible.has(id)).map(loadProgress)]);
  } catch(error) {$("#connection").classList.add("offline");$("#connection").textContent="Offline · showing last update";$("#notice").textContent="The local background service is unavailable. Run your PigentHub start shortcut to reconnect.";$("#side-state").textContent="Offline · showing last update";}
  finally {syncing=false;$("#refresh").disabled=false;}
}
let renderPending=false;
function typingInCard() { const active=document.activeElement;return Boolean(active?.matches?.(".card textarea")&&active.value); }
document.addEventListener("focusout",event=>{if(event.target.matches?.(".card textarea")&&renderPending)setTimeout(()=>{if(!typingInCard()){renderPending=false;render();}},0);});
function tick() {
  const now=new Date();
  $("#side-clock").textContent=now.toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit"});
  $("#side-date").textContent=now.toLocaleDateString("en-GB",{weekday:"short",day:"numeric",month:"short"});
  for(const timer of document.querySelectorAll(".answer-timer[data-until]"))timer.textContent=remaining(Number(timer.dataset.until));
}
document.querySelectorAll(".filter").forEach(button=>button.onclick=()=>{source=button.dataset.source;document.querySelectorAll(".filter").forEach(b=>b.setAttribute("aria-pressed",String(b===button)));render();});
$("#search").oninput=event=>{query=event.target.value.trim().toLowerCase();render();};
$("#refresh").onclick=sync;$("#close").onclick=closeDetail;$("#backdrop").onclick=closeDetail;
document.addEventListener("keydown",event=>{
  if(!selected) {if(event.key==="Escape"){const card=document.activeElement?.closest(".card");if(card&&expanded.has(card.dataset.id)){toggleProgress(card.dataset.id);focusCard(card.dataset.id);}}return;}
  if(event.key==="Escape")closeDetail();

});
async function poll() {await sync();setTimeout(poll,3000);}
tick();setInterval(tick,1000);
poll();
