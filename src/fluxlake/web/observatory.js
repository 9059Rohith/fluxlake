/* Deterministic, data-backed rendering helpers. No provider calls or sample fixtures. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.FluxObservatory = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const icon = name => `<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><use href="/assets/icons.svg#${/^[a-z]+$/.test(name) ? name : "file"}"/></svg>`;
  const number = value => Number(value || 0).toLocaleString("en-US");
  const valueOf = value => Number.isFinite(Number(value)) ? Math.max(0,Number(value)) : 0;
  const tone = (name,index=0) => ({PushEvent:0,CreateEvent:1,DeleteEvent:2,PullRequestEvent:3}[name] ?? index%4);
  const typeHref = name => `/workspace/silver?event_type=${encodeURIComponent(name)}`;

  function composition(rows, mode="count") {
    if (!rows.length) return '<div class="chart-empty">No event types have been acquired.</div>';
    const total=rows.reduce((sum,row)=>sum+valueOf(row.events),0);
    const peak=Math.max(...rows.map(r=>valueOf(r.events)));
    const max=mode==="share"?100:peak<=5?5:peak<=20?Math.ceil(peak/5)*5:peak<=100?Math.ceil(peak/20)*20:Math.ceil(peak/50)*50;
    const left=44, top=26, width=628, height=213, bottom=top+height;
    const slot=width/rows.length, bar=Math.min(78,slot*.56);
    const grid=Array.from({length:6},(_,i)=>{const y=top+i*height/5;return `<g class="chart-grid"><line x1="${left}" y1="${y}" x2="${left+width}" y2="${y}"/><text x="${left-12}" y="${y+4}" text-anchor="end">${number(max-i*max/5)}${mode==="share"?"%":""}</text></g>`;}).join("");
    const bars=rows.map((row,i)=>{const count=valueOf(row.events),share=total?count/total*100:0,value=mode==="share"?share:count;
      const h=value/max*height,x=left+slot*i+(slot-bar)/2,y=bottom-h;
      const valueId = `composition-value-${i}`;
      const labelId = `composition-label-${i}`;
      return `<a class="chart-link" href="${typeHref(row.event_type)}" aria-labelledby="${valueId} ${labelId}"><title>${escapeHtml(row.event_type)}: ${count} events, ${share.toFixed(1)}% of retained sample</title><rect class="plot-bar tone-${tone(row.event_type,i)}" x="${x}" y="${y}" width="${bar}" height="${Math.max(1,h)}" rx="2"/><text id="${valueId}" class="chart-value" x="${x+bar/2}" y="${Math.max(16,y-10)}" text-anchor="middle">${number(count)} (${Number(share.toFixed(1))}%)</text><text id="${labelId}" class="chart-label" x="${x+bar/2}" y="${bottom+28}" text-anchor="middle">${escapeHtml(row.event_type)}</text></a>`;
    }).join("");
    return `<svg class="composition-chart" viewBox="0 0 700 285" role="group" aria-label="Event composition of ${total} actual retained events">${grid}<line class="chart-axis" x1="${left}" y1="${bottom}" x2="${left+width}" y2="${bottom}"/>${bars}</svg>`;
  }

  function typeStack(rows) {
    const total=rows.reduce((sum,row)=>sum+valueOf(row.events),0);
    if (!total) return '<p class="muted small">No observed distribution yet.</p>';
    let offset=0;
    const segments=rows.map((row,i)=>{const size=valueOf(row.events)/total*100;const x=offset;offset+=size;return `<a href="${typeHref(row.event_type)}" aria-label="Explore ${escapeHtml(row.event_type)}"><rect class="tone-${tone(row.event_type,i)}" x="${x}" y="0" width="${size}" height="8"><title>${escapeHtml(row.event_type)}: ${row.events}</title></rect></a>`;}).join("");
    return `<svg class="distribution-strip" viewBox="0 0 100 8" preserveAspectRatio="none" aria-label="Exact shares of the retained event types">${segments}</svg><div class="distribution-legend">${rows.map((row,i)=>`<a href="${typeHref(row.event_type)}"><span class="legend-dot tone-${tone(row.event_type,i)}"></span><span>${escapeHtml(row.event_type)}</span><strong>${number(row.events)} <small>(${Number((valueOf(row.events)/total*100).toFixed(1))}%)</small></strong></a>`).join("")}</div>`;
  }

  function rankChart(rows, group) {
    if (!rows.length) return '<div class="chart-empty">No aggregate observations yet.</div>';
    const shown=rows.slice(0,10),max=Math.max(1,...shown.map(r=>valueOf(r.events))),height=shown.length*36+25;
    return `<svg class="rank-chart" viewBox="0 0 620 ${height}" role="group" aria-label="Top retained-sample ${escapeHtml(group)} counts">${shown.map((row,i)=>{
      const q=new URLSearchParams({[group==="event_type"?"event_type":"q"]:String(row.dimension).slice(0,100)});
      return `<a href="/workspace/silver?${escapeHtml(q.toString())}" class="chart-link"><title>${escapeHtml(row.dimension)}: ${number(row.events)} actual events</title><text class="chart-label" x="0" y="${i*36+18}">${escapeHtml(row.dimension.length>27?row.dimension.slice(0,26)+"…":row.dimension)}</text><rect class="rank-track" x="215" y="${i*36+6}" width="350" height="16" rx="2"/><rect class="tone-${i%4}" x="215" y="${i*36+6}" width="${valueOf(row.events)/max*350}" height="16" rx="2"/><text class="chart-value" x="590" y="${i*36+19}" text-anchor="end">${number(row.events)}</text></a>`;
    }).join("")}</svg>`;
  }

  function driftPlot(rows) {
    const height=rows.length*45+40,left=120,width=440;
    return `<svg class="drift-plot" viewBox="0 0 610 ${height}" role="img" aria-label="Observed baseline and candidate event-type shares">${[0,25,50,75,100].map(t=>`<g class="chart-grid"><line x1="${left+t/100*width}" y1="10" x2="${left+t/100*width}" y2="${height-30}"/><text x="${left+t/100*width}" y="${height-8}" text-anchor="middle">${t}%</text></g>`).join("")}${rows.map((r,i)=>{const y=25+i*45,a=left+valueOf(r.baseline_share)*width,b=left+valueOf(r.candidate_share)*width;return `<g><title>${escapeHtml(r.event_type)}: baseline ${(r.baseline_share*100).toFixed(1)}%, candidate ${(r.candidate_share*100).toFixed(1)}%</title><text class="chart-label" x="0" y="${y+4}">${escapeHtml(r.event_type.replace(/Event$/,""))}</text><line class="drift-connector" x1="${a}" y1="${y}" x2="${b}" y2="${y}"/><circle class="tone-0" cx="${a}" cy="${y}" r="5"/><circle class="tone-1" cx="${b}" cy="${y}" r="5"/></g>`;}).join("")}</svg>`;
  }

  function sortRecords(rows, key, direction="asc") {
    const collator=new Intl.Collator("en",{numeric:true,sensitivity:"base"}),factor=direction==="desc"?-1:1;
    return rows.map((value,index)=>({value,index})).sort((a,b)=>factor*collator.compare(String(a.value[key]??""),String(b.value[key]??""))||a.index-b.index).map(row=>row.value);
  }

  function inline(raw) {
    const pattern=/(\[[^\]\n]+\]\([^\)\n]+\)|`[^`\n]+`|\*\*[^*\n]+\*\*|\/api\/workspace\/[A-Za-z0-9_?=&%./-]+)/g;
    let last=0,html="",match;
    while((match=pattern.exec(raw))){html+=escapeHtml(raw.slice(last,match.index));const value=match[0];
      if(value[0]==="`")html+=`<code>${escapeHtml(value.slice(1,-1))}</code>`;
      else if(value.startsWith("**"))html+=`<strong>${escapeHtml(value.slice(2,-2))}</strong>`;
      else if(value.startsWith("[")){const link=value.match(/^\[([^\]]+)\]\(([^)]+)\)$/);html+=link&&/^\/api\/workspace\/[A-Za-z0-9_?=&%./-]*$/.test(link[2])?`<a class="answer-source" href="${escapeHtml(link[2])}" target="_blank" rel="noopener">${escapeHtml(link[1])}</a>`:escapeHtml(value);}
      else{const path=value.replace(/[.,]+$/,"");html+=`<a class="answer-source" href="${escapeHtml(path)}" target="_blank" rel="noopener">${escapeHtml(path)}</a>${escapeHtml(value.slice(path.length))}`;}
      last=pattern.lastIndex;
    }
    return html+escapeHtml(raw.slice(last));
  }

  function renderMarkdown(input) {
    const lines=String(input??"").slice(0,24000).replace(/\r\n/g,"\n").split("\n");
    let html="",paragraph=[],list=[],listTag="ul",code=null;
    const flushParagraph=()=>{if(paragraph.length){html+=`<p>${inline(paragraph.join(" "))}</p>`;paragraph=[];}};
    const flushList=()=>{if(list.length){html+=`<${listTag}>${list.map(value=>`<li>${inline(value)}</li>`).join("")}</${listTag}>`;list=[];}};
    for(const line of lines){
      if(/^\s*```/.test(line)){flushParagraph();flushList();if(code===null)code=[];else{html+=`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`;code=null;}continue;}
      if(code!==null){code.push(line);continue;}
      if(!line.trim()){flushParagraph();flushList();continue;}
      const heading=line.match(/^#{1,3}\s+(.+)$/),bullet=line.match(/^\s*[-*]\s+(.+)$/),ordered=line.match(/^\s*\d+[.)]\s+(.+)$/);
      if(heading){flushParagraph();flushList();html+=`<h3>${inline(heading[1])}</h3>`;}
      else if(bullet||ordered){flushParagraph();const tag=ordered?"ol":"ul";if(list.length&&tag!==listTag)flushList();listTag=tag;list.push((bullet||ordered)[1]);}
      else{flushList();paragraph.push(line.trim());}
    }
    flushParagraph();flushList();if(code!==null)html+=`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`;
    return html;
  }
  return {escapeHtml,icon,composition,typeStack,rankChart,driftPlot,sortRecords,renderMarkdown};
});
