/* Typed Field Station evidence stays separate from documentary mentions. */
(function (root) {
  'use strict';
  function index(section = {}) {
    const nodes = new Map((section.nodes || []).map(n => [n.id, n]));
    const locations = new Map();
    for (const e of section.edges || []) if (e.relation === 'located_in') {
      if (!locations.has(e.source)) locations.set(e.source, new Set());
      locations.get(e.source).add(e.target);
    }
    const recordings = new Map();
    for (const o of section.observations || []) for (const id of o.recordingIds || []) {
      const n = nodes.get(id); if (!n || n.type !== 'recording') continue;
      if (!recordings.has(id)) recordings.set(id, {...n, observations: new Set(), objects: new Set(), regions: new Set(), bundles: new Map()});
      const r = recordings.get(id); r.observations.add(o.id);
      for (const region of locations.get(o.id) || []) r.regions.add(region);
      for (const b of o.evidence || []) if (b.recordingId === n.recordingId) {
        const old = r.bundles.get(b.nodeId);
        if (!old || b.verifiedEpoch > old.verifiedEpoch) r.bundles.set(b.nodeId, {...b, url: nodes.get(b.nodeId)?.url});
      }
    }
    for (const e of section.edges || []) if (e.relation === 'reviewed_frame_in') recordings.get(e.target)?.objects.add(e.source);
    return {nodes, recordings: [...recordings.values()].sort((a,b)=>(b.startedEpoch || 0)-(a.startedEpoch || 0)), regions: section.regions || []};
  }
  function clock(recordings, period = 'all') {
    return recordings.filter(r => Number.isFinite(r.startedEpoch)).map(r => {
      const d = new Date(r.startedEpoch * 1000), hour = d.getUTCHours();
      return {recording:r, minuteOfDial: (hour % 12)*60 + d.getUTCMinutes(), period: hour < 12 ? 'am':'pm', documentId:r.id, source:'starpeople.ai Field Station'};
    }).filter(r => period === 'all' || r.period === period);
  }
  function spectra(text) {
    const snapshots = new Map();
    function add(s, captured) {
      if (!s || typeof s !== 'object') return;
      const range=s.range_hz, values=s.average_db;
      if (Array.isArray(range) && range.length===2 && range.every(Number.isFinite) && range[1]>range[0] && Array.isArray(values) && values.length>1 && values.length<=10000 && values.some(Number.isFinite)) {
        const stamp=s.minute_utc || captured || '', key=JSON.stringify([stamp,range,s.device_serial || '']);
        snapshots.set(key,{stamp,range,average:values.map(v=>Number.isFinite(v)?v:null),maximum:Array.isArray(s.maximum_db) && s.maximum_db.length===values.length?s.maximum_db.map(v=>Number.isFinite(v)?v:null):[]});
      }
      // Receiver summaries are bounded to this schema; never walk arbitrary nested data.
      if (s.receivers) for (const receiver of Object.values(s.receivers)) {
        if (receiver && typeof receiver==='object') {
          const copy={...(receiver.spectrum || receiver)}; delete copy.receivers; add(copy,captured);
        }
      }
    }
    for (const line of text.split('\n')) {
      if (!line.trim()) continue;
      const row=JSON.parse(line); add(row.spectrum,row.captured_at);
    }
    return [...snapshots.values()].sort((a,b)=>a.stamp.localeCompare(b.stamp));
  }
  const api={index,clock,spectra};
  if(typeof module !== 'undefined' && module.exports) module.exports=api;
  else root.FieldEvidence=api;
})(globalThis);
