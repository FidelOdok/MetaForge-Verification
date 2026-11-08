const el = id => document.getElementById(id);
let active = null, generation = 0;
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
    await history(job);
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
