"use strict";

/** 依赖：浏览器DOM/fetch/History；输入：纯数据磁贴配置；输出：启动画面和持久功能面板；实现：展示层隔离作用域，既有workspace独占业务与写入。 */
(() => {
  const views = new Set(["home", "write", "resources", "memory", "activity", "settings", "about", "placeholder"]);
  const actions = {workbench:"write",outline:"write",harness:"write",resources:"resources",preferences:"resources",memory:"memory",activity:"activity",settings:"settings",about:"about",overview:"about",placeholder:"placeholder"};
  const titles = {write:"创作工作台",resources:"世界、人物与前文",memory:"旧事与伏笔",activity:"本轮活动",settings:"空间设置",about:"此刻的工作区",placeholder:"新的空间"};
  const storeKey = "novel-rag.launcher.preferences.v1";
  const state = {tiles:[],assets:new Map(),active:"home",origin:null,homeScroll:0,timer:null,ticks:0,observer:null,allowMotion:true};

  /** 依赖：原生DOM；输入：标签/类/可选纯文本；输出：新节点；实现：只设置textContent，不解释配置HTML。 */
  function node(tag, className="", text="") { const value=document.createElement(tag); value.className=className; if(text)value.textContent=text; return value; }

  /** 依赖：配置合同；输入：JSON；输出：已验证tiles或错误；实现：限制文字/色值/数值网格和唯一ID，未知action保留占位而不执行代码。 */
  function validateTiles(config) {
    if(config?.version!==1||!Array.isArray(config.tiles)||!config.tiles.length||config.tiles.length>32)throw new Error("磁贴配置格式不可用。");
    const ids=new Set(); const occupied=new Set();
    for(const tile of config.tiles){
      if(!/^[a-z][a-z0-9-]{0,40}$/.test(tile.id)||ids.has(tile.id))throw new Error("磁贴编号缺失或重复。");
      ids.add(tile.id);
      for(const field of ["title","subtitle","eyebrow"])if(typeof tile[field]!=="string"||tile[field].length>160)throw new Error("磁贴文案需要是短文本。");
      if(!/^#[\da-f]{6}$/i.test(tile.color))throw new Error("磁贴颜色需要是六位色值。");
      if(!["hero","primary","navigation","feature","compact"].includes(tile.kind))throw new Error("磁贴类型不可用。");
      if(typeof tile.action!=="string"||tile.action.length>60)throw new Error("磁贴入口不可用。");
      const g=tile.grid;
      if(!g||![g.column,g.columnSpan,g.row,g.rowSpan].every(v=>Number.isInteger(v)&&v>0)||g.column+g.columnSpan>13||g.row+g.rowSpan>7)throw new Error("磁贴超出桌面网格。");
      if(tile.mobileSpan!==undefined&&(!Number.isInteger(tile.mobileSpan)||tile.mobileSpan<1||tile.mobileSpan>6))throw new Error("移动磁贴跨度不可用。");
      if(tile.images!==undefined&&(!Array.isArray(tile.images)||tile.images.length>4||tile.images.some(id=>typeof id!=="string")))throw new Error("磁贴图片需要是资源编号。");
      if(tile.imagePosition!==undefined&&!/^\d{1,3}% \d{1,3}%$/.test(tile.imagePosition))throw new Error("图片位置需要是百分比。");
      for(let row=g.row;row<g.row+g.rowSpan;row++)for(let col=g.column;col<g.column+g.columnSpan;col++){const key=`${row}:${col}`;if(occupied.has(key))throw new Error("磁贴位置重叠。");occupied.add(key);}
    }
    return config.tiles;
  }

  /** 依赖：同源静态资源；输入：资源manifest及可选imagePosition；输出：安全资源Map；实现：仅接受本地图片和0–100百分比焦点，无合法焦点时继承磁贴构图。 */
  function validateAssets(manifest) {
    const assets=new Map();
    for(const asset of Array.isArray(manifest?.assets)?manifest.assets:[]){
      if(typeof asset.id!=="string"||!/^[a-z][a-z0-9-]*$/.test(asset.id)||typeof asset.file!=="string"||!/^[-a-zA-Z0-9]+\.(?:png|jpg|jpeg|webp)$/.test(asset.file))continue;
      const position=/^(?:100|\d{1,2})% (?:100|\d{1,2})%$/.test(asset.imagePosition)?asset.imagePosition:null;
      assets.set(asset.id,{...asset,imagePosition:position,url:`/static/assets/${asset.file}`});
    }
    return assets;
  }

  /** 依赖：原生图片；输入：error事件；输出：失效图片隐藏、颜色降级；实现：不隐藏磁贴或取消入口，轮换跳过失败帧。 */
  function imageFailed(event) { event.currentTarget.dataset.failed="true";event.currentTarget.hidden=true;event.currentTarget.classList.remove("active"); }

  /** 依赖：DOM/验证后的tiles/assets；输入：tile和顺序；输出：完整按钮；实现：独立色块、原图及每图焦点、文字和时钟，按原生按钮与既有轮换展示。 */
  function renderTile(tile,index) {
    const button=node("button","tile"); button.type="button";button.dataset.tile=tile.id;button.dataset.action=tile.action;button.dataset.kind=tile.kind;
    button.setAttribute("aria-label",tile.title);button.style.setProperty("--tile-color",tile.color);
    for(const [name,value] of Object.entries(tile.grid))button.style.setProperty({column:"--tile-column",columnSpan:"--tile-column-span",row:"--tile-row",rowSpan:"--tile-row-span"}[name],String(value));
    button.style.setProperty("--mobile-span",String(tile.mobileSpan??3));
    if(tile.imagePosition)button.style.setProperty("--image-position",tile.imagePosition);
    const images=node("span","tile-image");
    for(const id of tile.images??[]){const asset=state.assets.get(id);if(!asset)continue;const image=node("img");image.src=asset.url;image.alt="";image.decoding="async";image.draggable=false;if(asset.imagePosition)image.style.objectPosition=asset.imagePosition;image.addEventListener("error",imageFailed);if(!images.children.length)image.classList.add("active");images.append(image);}
    button.append(images,node("span","tile-shade"));
    const top=node("span","tile-top");top.append(node("span","tile-eyebrow",tile.eyebrow),node("span","tile-index",String(index+1).padStart(2,"0")));button.append(top);
    const content=node("span","tile-content");
    if(tile.kind==="hero") { const date=node("span","hero-date");date.dataset.date="";const clock=node("span","hero-clock");clock.dataset.clock="";clock.setAttribute("role","timer");clock.setAttribute("aria-live","off");content.append(date,clock,node("span","hero-caption",tile.subtitle)); const status=node("span","tile-meta");status.dataset.workspaceStatus="";content.append(status); }
    else {content.append(node("span","tile-title",tile.title),node("span","tile-description",tile.subtitle));if(tile.kind==="primary"){const story=node("span","tile-meta");story.dataset.workspaceStory="";content.append(story);}}
    button.append(content,node("span","tile-arrow","↗"));return button;
  }

  /** 依赖：持久DOM；输入：当前view和是否改URL；输出：可见面板、返回焦点；实现：只改新增外层hidden，保留run查询参数，不触碰业务生命周期。 */
  function showView(view,{history=true,focus=true}={}) {
    if(!views.has(view))view="home";
    const changed=state.active!==view;
    if(changed&&state.active==="home")state.homeScroll=window.scrollY;
    state.active=view;document.body.dataset.view=view;
    document.getElementById("launcherView").hidden=view!=="home";
    document.getElementById("workspaceView").hidden=view==="home";
    document.querySelectorAll(".surface[data-surface]").forEach(surface=>{surface.hidden=surface.dataset.surface!==view;});
    if(view!=="home")document.getElementById("surfaceTitle").textContent=titles[view];
    if(history&&location.hash!==`#${view}`){const url=new URL(location.href);url.hash=view;window.history.pushState({mosaicView:view},"",url);}
    if(changed){document.getElementById("workspaceBody").scrollTop=0;window.scrollTo({top:view==="home"?state.homeScroll:0,behavior:"instant"});}
    if(focus){if(view==="home") { const origin=state.origin?.isConnected?state.origin:document.querySelector(".tile")??document.querySelector("#launcherFallback h1");origin?.focus({preventScroll:true}); }else document.getElementById("surfaceTitle").focus({preventScroll:true});}
    manageClock();updateSummary();
  }

  /** 依赖：展示动作Map与既有表单；输入：action/tile；输出：对应视图/占位；实现：切页不创建run，外部工具只选择现有driver，历史修改仍归workspace。 */
  function openAction(action,tile=null) {
    state.origin=tile?document.querySelector(`[data-tile="${tile.id}"]`):state.origin;
    const view=Object.hasOwn(actions,action)?actions[action]:"placeholder";
    if(view==="placeholder"){document.getElementById("placeholderTitle").textContent=tile?.title??"新的空间";document.getElementById("placeholderDescription").textContent=tile?.subtitle??"这个磁贴暂时没有对应功能。";}
    showView(view);
    if(action==="harness"){const driver=document.getElementById("driverSelect");driver.value="harness";driver.dispatchEvent(new Event("change",{bubbles:true}));document.getElementById("harnessPanel").open=true;}
    if(action==="outline")document.getElementById("outlineInput").focus();
    if(action==="preferences"){
      document.getElementById("resourcesPanel").open=true;
      const editor=document.getElementById("preferencesEditor");
      (editor.disabled?document.getElementById("preferencesTitle"):editor).focus();
    }
  }

  /** 依赖：浏览器时间/轮换图片；输入：无；输出：当前时钟与可选缓慢轮图；实现：时钟从Date重算，减少动态或偏好关闭时不切图。 */
  function tick() {
    const now=new Date();
    document.querySelectorAll("[data-clock]").forEach(clock=>{clock.textContent=new Intl.DateTimeFormat("zh-CN",{hour:"2-digit",minute:"2-digit",hour12:false}).format(now);});
    document.querySelectorAll("[data-date]").forEach(date=>{date.textContent=new Intl.DateTimeFormat("zh-CN",{month:"long",day:"numeric",weekday:"long"}).format(now);});
    state.ticks+=1;
    if(state.ticks%45||!state.allowMotion||matchMedia("(prefers-reduced-motion: reduce)").matches)return;
    document.querySelectorAll(".tile-image").forEach(host=>{const images=[...host.querySelectorAll('img:not([data-failed="true"])')];if(images.length<2)return;const current=images.findIndex(image=>image.classList.contains("active"));images.forEach((image,index)=>image.classList.toggle("active",index===(current+1)%images.length));});
  }

  /** 依赖：文档可见性/时钟；输入：无；输出：唯一展示timer；实现：首页可见才更新，隐藏/离开暂停，不关闭模型SSE。 */
  function manageClock() {clearInterval(state.timer);state.timer=null;if(state.active==="home"&&!document.hidden){tick();state.timer=setInterval(tick,1000);}}

  /** 依赖：workspace已渲染DOM；输入：无；输出：首页与概览实时摘要；实现：读取同一业务状态文案，MutationObserver只观察呈现，不建立第二订阅流。 */
  function updateSummary() {
    const status=document.getElementById("runStatus").textContent;
    const selection=document.getElementById("storySelect");const story=selection.selectedOptions[0]?.textContent??"选择作品，开始下一页。";
    const error=document.getElementById("errorBanner");const edit=document.getElementById("draftEditState").textContent;
    const label=!error.hidden?error.textContent:edit.includes("未保存")?edit:status;
    document.querySelectorAll("[data-workspace-status]").forEach(node=>{node.textContent=label;});
    document.querySelectorAll("[data-workspace-story]").forEach(node=>{node.textContent=story;});
    document.getElementById("overviewStatus").textContent=label;document.getElementById("overviewStory").textContent=story;
  }

  /** 依赖：DOM/事件；输入：click；输出：短反馈与打开面板；实现：原生整磁贴点击，未知动作只进占位，无文学审批或隐式模型调用。 */
  function onClick(event) {
    const button=event.target.closest("button");if(!button)return;
    if(button.id==="homeButton")showView("home");
    else if(button.dataset.launch)openAction(button.dataset.launch);
    else if(button.dataset.tile){button.classList.add("is-pressed");setTimeout(()=>button.classList.remove("is-pressed"),160);openAction(button.dataset.action,state.tiles.find(tile=>tile.id===button.dataset.tile));}
  }

  /** 依赖：实际磁贴矩形/原生dialog/键盘；输入：keydown；输出：相邻磁贴焦点或返回；实现：dialog及已处理事件交给原owner，其余按视觉方向选按钮，文本输入不被抢键。 */
  function onKey(event) {
    if(event.defaultPrevented||event.target.closest("dialog[open]"))return;
    if(event.key==="Escape"&&state.active!=="home"&& !event.target.closest("input,textarea,select")){event.preventDefault();showView("home");return;}
    const tile=event.target.closest(".tile");const directions={ArrowRight:[1,0],ArrowLeft:[-1,0],ArrowDown:[0,1],ArrowUp:[0,-1]};
    if(!tile||!directions[event.key])return;
    const [dx,dy]=directions[event.key],a=tile.getBoundingClientRect(),x=a.x+a.width/2,y=a.y+a.height/2;
    let best=null,distance=Infinity;
    for(const candidate of document.querySelectorAll(".tile")){if(candidate===tile)continue;const b=candidate.getBoundingClientRect(),vx=b.x+b.width/2-x,vy=b.y+b.height/2-y;if(dx*vx+dy*vy<=0)continue;const score=Math.hypot(vx,vy)+Math.abs(dx*vy-dy*vx)*2;if(score<distance){distance=score;best=candidate;}}
    if(best){event.preventDefault();best.focus();}
  }

  /** 依赖：当前URL；输入：无；输出：展示入口；实现：有效hash优先，只有run查询时恢复工作台。 */
  function locationView() {
    const desired=location.hash.slice(1);
    return views.has(desired)?desired:new URLSearchParams(location.search).has("run")?"write":"home";
  }

  /** 依赖：History/hash；输入：hashchange/popstate；输出：展示相应持久面板；实现：沿用初始深链入口，保留查询串与当前任务。 */
  function onHistory() {showView(locationView(),{history:false});}

  /** 依赖：同步CustomEvent；输入：workspace:navigate detail；输出：先展开写作再聚焦；实现：只接受白名单view和已存在id，不复制业务基线操作。 */
  function onNavigate(event) {if(!views.has(event.detail?.view))return;showView(event.detail.view);document.getElementById(event.detail.focusId)?.focus();}

  /** 依赖：本地偏好/减少动态；输入：checkbox change；输出：唯一展示设置；实现：独立key写入，仅失败时保留当前页面偏好。 */
  function setMotion(event) {state.allowMotion=event.target.checked;try{localStorage.setItem(storeKey,JSON.stringify({allowMotion:state.allowMotion}));}catch{} }

  /** 依赖：asset来源字段/DOM；输入：无；输出：可点击画师出处；实现：来源HTTPS链接安全呈现，不把远程素材作为运行依赖。 */
  function renderCredits() {
    const host=document.getElementById("assetCredits");host.replaceChildren();
    for(const asset of state.assets.values()){const item=node("li");item.append(node("strong","",asset.title??asset.id),node("span","",asset.artist??"作者见原帖"));try{const url=new URL(asset.source);if(url.protocol==="https:"){const link=node("a","","原帖与画师 ↗");link.href=url.href;link.target="_blank";link.rel="noreferrer noopener";item.append(link);}}catch{}host.append(item);}
  }

  /** 依赖：静态fetch/配置/资源；输入：无；输出：配置磁贴或真实工作区兜底；实现：资源清单故障独立降级，配置失败不阻止workspace启动。 */
  async function loadLauncher() {
    const configPromise=fetch("/static/tiles.json").then(response=>{if(!response.ok)throw new Error("磁贴配置暂时无法读取。");return response.json();});
    const assetsPromise=fetch("/static/assets/manifest.json").then(response=>response.ok?response.json():{}).catch(()=>({}));
    try {const [config,manifest]=await Promise.all([configPromise,assetsPromise]);state.tiles=validateTiles(config);state.assets=validateAssets(manifest);document.getElementById("tileGrid").replaceChildren(...state.tiles.map(renderTile));document.getElementById("launcherFallback").hidden=true;renderCredits();manageClock();updateSummary();}
    catch(error){document.getElementById("launcherLoadState").textContent=`${error.message} 你仍可进入创作工作台。`;}
  }

  /** 依赖：DOM事件/MutationObserver；输入：DOMContentLoaded；输出：单一展示生命周期；实现：一次绑定，业务节点不重建，深链直接进入写作。 */
  function initialize() {
    try{const settings=JSON.parse(localStorage.getItem(storeKey)||"{}");if(typeof settings.allowMotion==="boolean")state.allowMotion=settings.allowMotion;}catch{}
    document.getElementById("motionPreference").checked=state.allowMotion;
    document.getElementById("motionPreference").addEventListener("change",setMotion);
    document.addEventListener("click",onClick);document.addEventListener("keydown",onKey);document.addEventListener("workspace:navigate",onNavigate);document.addEventListener("visibilitychange",manageClock);
    window.addEventListener("hashchange",onHistory);window.addEventListener("popstate",onHistory);
    state.observer=new MutationObserver(updateSummary);
    for(const id of ["runStatus","draftEditState","errorBanner","storySelect"])state.observer.observe(document.getElementById(id),{childList:true,subtree:true,attributes:true,attributeFilter:["hidden","data-state"]});
    document.getElementById("storySelect").addEventListener("change",updateSummary);
    window.addEventListener("pagehide",()=>{clearInterval(state.timer);state.timer=null;});window.addEventListener("pageshow",manageClock);
    showView(locationView(),{history:false,focus:false});
    loadLauncher();
  }
  window.addEventListener("DOMContentLoaded",initialize,{once:true});
})();
