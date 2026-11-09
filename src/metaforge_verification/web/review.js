const el = id => document.getElementById(id);
let active = null, generation = 0;
const requestedJob = new URLSearchParams(location.search).get('job');
if (/^[a-f0-9-]{36}$/.test(requestedJob || '')) el('job').value = requestedJob;
const text = (tag, value) => { const node = document.createElement(tag); node.textContent = value; return node; };
async function api(path, options = {}) {
  const response = await fetch(path, {...options, cache:'no-store', credentials:'omit',
    headers:{'Authorization':`Bearer ${el('token').value}`, 'Content-Type':'application/json'}});
  if (!response.ok) throw new Error(`Request returned ${response.status}: ${JSON.stringify((await response.json()).detail)}`);
  return response.json();
}
async function history(job) {
  const result = await api(`/v1/verifications/${encodeURIComponent(job)}/reviews`);
  if (active === job) el('history').textContent = JSON.stringify(result.items, null, 2);
}
async function previews(report, attempt) {
  el('captures').replaceChildren();
  const evidence = report.evidence.find(e=>e.method==='visual.render_regression') || report.evidence.find(e=>e.method==='visual.render_capture');
  if (!evidence) return;
  const capture = evidence.details.capture || evidence.details;
  for (const view of ['front','side','top','iso']) {
    const asset = capture.images?.[view]; if (!asset) continue;
    const response = await fetch(`/v1/artifacts/${encodeURIComponent(asset.artifact_id)}`, {cache:'no-store',credentials:'omit',headers:{Authorization:`Bearer ${el('token').value}`}});
    if (!response.ok || attempt !== generation) return;
    const bytes = await response.arrayBuffer();
    if (attempt !== generation) return;
    const url = URL.createObjectURL(new Blob([bytes],{type:'image/png'}));
    try {
      const image = new Image(); image.src=url; await image.decode();
      if (attempt !== generation) return;
      const figure=document.createElement('figure'), canvas=document.createElement('canvas');
      canvas.width=512;canvas.height=512;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
      const change=evidence.details.differences?.find(d=>d.view===view);
      if(change?.difference_bbox){const [x0,y0,x1,y1]=change.difference_bbox;ctx.strokeStyle='#c5283d';ctx.lineWidth=3;ctx.strokeRect(x0,y0,x1-x0,y1-y0);}
      figure.append(canvas,text('figcaption',view+(change ? ` · ${(100*change.changed_fraction).toFixed(2)}% pixels changed` : '')));el('captures').append(figure);
    } finally {URL.revokeObjectURL(url);}
  }
}
el('load').addEventListener('submit', async event => {
  event.preventDefault(); const attempt = ++generation; active = null; el('result').hidden = true;
  const job = el('job').value.trim(); el('status').textContent = 'Loading report…';
  try {
    const report = await api(`/v1/verifications/${encodeURIComponent(job)}/report`);
    if (attempt !== generation) return;
    active = job; el('gate').textContent = report.gate_decision; el('gate').dataset.outcome = report.gate_decision;
    el('revision').textContent = `${report.twin_id} / ${report.revision_id}`; el('profile').textContent = report.profile_id;
    el('findings').replaceChildren(); el('requirement').replaceChildren();
    for (const finding of report.findings) {
      const row = document.createElement('tr'); const criterion = finding.criterion;
      const measured = finding.measurement ? `${finding.measurement.value} ${finding.measurement.unit}` : 'No accepted measurement';
      const target = criterion ? ` · ${criterion.operator} ${criterion.threshold.value} ${criterion.threshold.unit}` : '';
      for (const value of [finding.requirement_id, finding.outcome, measured + target, finding.achieved_fidelity || 'Unassessed', finding.reason]) row.append(text('td', value));
      el('findings').append(row); const option = text('option', finding.requirement_id); option.value = finding.requirement_id; el('requirement').append(option);
    }
    el('evidence').replaceChildren();
    for (const evidence of report.evidence) {
      const details = document.createElement('details'); details.append(text('summary', `${evidence.method} · ${evidence.tool_version}`), text('pre', JSON.stringify(evidence, null, 2))); el('evidence').append(details);
    }
    el('coverage').textContent = JSON.stringify(report.coverage, null, 2); el('limitations').replaceChildren(...report.limitations.map(value => text('li', value)));
    el('result').hidden = false; el('status').textContent = 'Report loaded. Evidence details retain sources, geometry locations and visual regions.';
    await history(job); await previews(report,attempt);
  } catch (error) { if (attempt === generation) el('status').textContent = error.message; }
});
el('token').addEventListener('input', () => { generation++; active = null; el('result').hidden = true; });
el('review').addEventListener('submit', async event => {
  event.preventDefault(); if (!active) return; const job = active;
  try {
    await api(`/v1/verifications/${encodeURIComponent(job)}/reviews`, {method:'POST',body:JSON.stringify({requirement_id:el('requirement').value,decision:el('decision').value,rationale:el('rationale').value})});
    el('status').textContent = 'Review recorded. The engineering report remains unchanged.'; await history(job);
  } catch(error) { el('status').textContent = error.message; }
});
