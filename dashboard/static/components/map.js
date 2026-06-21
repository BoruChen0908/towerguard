// map.js — Leaflet map: aircraft markers, conflict highlighting, range ring
//
// Markers animate via client-side dead reckoning: between the 60 s-apart
// snapshots a 1 s tick extrapolates each aircraft along its last-known
// heading/velocity (constant-velocity straight line — the same assumption the
// backend conflict module uses). A CSS transform transition smooths each step.

const NM_TO_M = 1852; // nautical mile -> meters
const RANGE_NM = 50;

// --- dead-reckoning constants ---
const TICK_MS = 1000; // extrapolation cadence
const MAX_EXTRAPOLATE_S = 120; // never project further than this past a snapshot
const STALE_S = 90; // no fresh snapshot for this long → freeze (don't keep flying)
const NM_PER_DEG_LAT = 60.0; // matches conflict_geometry._NM_PER_DEG_LAT

// Approximate airport centers (lat, lon) for known demo airports.
// Falls back to first aircraft / world view if unknown.
const AIRPORTS = {
  KMDW: [41.7868, -87.7522],
  KJFK: [40.6413, -73.7781],
  KEWR: [40.6895, -74.1745],
  KBOS: [42.3656, -71.0096],
  KATL: [33.6407, -84.4277],
  KLGA: [40.7769, -73.8740],
  KLAX: [33.9425, -118.4081],
  KSFO: [37.6188, -122.375],
  KORD: [41.9742, -87.9073],
  KDFW: [32.8998, -97.0403],
  KDEN: [39.8561, -104.6737],
  KSEA: [47.4502, -122.3088],
  KLAS: [36.084, -115.1537],
  KMIA: [25.7932, -80.2906],
  KDCA: [38.8512, -77.0402],
  KCLT: [35.214, -80.9431],
};

/**
 * Dead-reckon a position forward from a snapshot anchor.
 * Heading is degrees clockwise from north (0°=N), constant velocity.
 *
 * @param {{lat:number, lon:number, velocity_kt:number, heading:number}} anchor
 * @param {number} dt_s seconds elapsed since the anchor snapshot
 * @returns {[number, number]} extrapolated [lat, lon]
 */
function extrapolate(anchor, dt_s) {
  const kt = Number(anchor.velocity_kt);
  const hdg = Number(anchor.heading);
  if (!Number.isFinite(kt) || !Number.isFinite(hdg) || kt <= 0) {
    return [anchor.lat, anchor.lon]; // no usable kinematics → hold position
  }
  const nm = (kt / 3600) * dt_s; // distance travelled (NM)
  const rad = (hdg * Math.PI) / 180;
  const dLat = (nm * Math.cos(rad)) / NM_PER_DEG_LAT;
  const cosLat = Math.cos((anchor.lat * Math.PI) / 180);
  const dLon =
    cosLat !== 0 ? (nm * Math.sin(rad)) / (NM_PER_DEG_LAT * cosLat) : 0;
  return [anchor.lat + dLat, anchor.lon + dLon];
}

export function createMap(elId) {
  const map = L.map(elId, {
    zoomControl: true,
    attributionControl: true,
    preferCanvas: true,
  }).setView([39.5, -98.35], 4); // continental US until first data

  L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    {
      attribution:
        '&copy; <a href="https://carto.com/">CARTO</a> &copy; OpenStreetMap contributors',
      subdomains: "abcd",
      maxZoom: 19,
    }
  ).addTo(map);

  // icao24 -> { marker, callsign, anchor:{lat,lon,velocity_kt,heading}, snapMs }
  const markers = new Map();
  let rangeRing = null;
  let airportMarker = null; // the glowing marker at the selected airport
  let conflictLines = [];
  let conflictPair = []; // callsigns of the active conflict pair, or []
  let centered = false;
  let airportCenter = null;

  function rotatedIcon(heading, isConflict) {
    const cls = `tg-ac${isConflict ? " is-conflict" : ""}`;
    const html = `<div class="${cls}" style="transform: rotate(${
      Number(heading) || 0
    }deg)"></div>`;
    return L.divIcon({
      className: "tg-ac-wrap",
      html,
      iconSize: [12, 14],
      iconAnchor: [6, 10],
    });
  }

  function tooltip(ac) {
    const cs = ac.callsign || ac.icao24 || "----";
    return (
      `<span class="tg-ac-cs">${cs}</span><br>` +
      `alt ${ac.alt_ft ?? "--"} ft<br>` +
      `spd ${ac.velocity_kt ?? "--"} kt`
    );
  }

  /** Set / refresh the 50NM range ring at the airport center.
   *  @param {boolean} [recenter] force the view to the new center even if the
   *         map was already centered (used by the airport switcher). */
  function setAirport(code, fallbackLatLon, recenter = false) {
    const center = AIRPORTS[code] || fallbackLatLon || null;
    if (!center) return;
    airportCenter = center;

    if (rangeRing) map.removeLayer(rangeRing);
    rangeRing = L.circle(center, {
      radius: RANGE_NM * NM_TO_M,
      color: "#2c3d50",
      weight: 1,
      opacity: 0.7,
      fillColor: "#0e3550",
      fillOpacity: 0.05,
      dashArray: "4 6",
      interactive: false,
    }).addTo(map);

    // Glowing marker at the selected airport so it lights up on the map.
    if (airportMarker) map.removeLayer(airportMarker);
    airportMarker = L.marker(center, {
      icon: L.divIcon({
        className: "tg-airport-wrap",
        html:
          '<div style="width:13px;height:13px;border-radius:50%;' +
          "background:#39c0ff;border:2px solid #d7f3ff;" +
          'box-shadow:0 0 14px 5px rgba(57,192,255,.85),0 0 5px 2px rgba(255,255,255,.9);">' +
          "</div>",
        iconSize: [13, 13],
        iconAnchor: [6, 6],
      }),
      interactive: false,
      zIndexOffset: 1000, // sits above aircraft markers
    }).addTo(map);

    if (!centered || recenter) {
      map.setView(center, 9);
      centered = true;
    }
  }

  /** Recenter on a known airport immediately (airport switch). Clears any
   *  stale fleet first so the old airport's markers don't linger mid-switch. */
  function recenterTo(code) {
    clearAircraft();
    setAirport(code, null, true);
  }

  /** Drop all aircraft markers + the conflict line (airport switch / reset). */
  function clearAircraft() {
    for (const [, entry] of markers) map.removeLayer(entry.marker);
    markers.clear();
    conflictPair = [];
    refreshConflictLine();
  }

  /** Current displayed position of an aircraft entry: the dead-reckoned point.
   *  Capped at MAX_EXTRAPOLATE_S; once stale (>STALE_S) the extrapolation is
   *  frozen at the STALE_S mark so a dropped feed doesn't fly markers away. */
  function displayLatLng(entry, nowMs) {
    const dt = (nowMs - entry.snapMs) / 1000;
    if (dt <= 0) return [entry.anchor.lat, entry.anchor.lon];
    const effective = dt > STALE_S ? STALE_S : Math.min(dt, MAX_EXTRAPOLATE_S);
    return extrapolate(entry.anchor, effective);
  }

  /** Redraw the conflict polyline from the current (animated) marker positions. */
  function refreshConflictLine() {
    for (const ln of conflictLines) map.removeLayer(ln);
    conflictLines = [];
    if (conflictPair.length !== 2) return;

    const pairSet = new Set(conflictPair);
    const positions = [];
    for (const [, entry] of markers) {
      if (entry.callsign && pairSet.has(entry.callsign)) {
        positions.push(entry.marker.getLatLng());
      }
    }
    if (positions.length === 2) {
      conflictLines.push(
        L.polyline(positions, {
          color: "#ff4d4d",
          weight: 2,
          opacity: 0.9,
          dashArray: "6 6",
          interactive: false,
        }).addTo(map)
      );
    }
  }

  /** 1 s dead-reckoning tick: advance every marker, then redraw the line. */
  function tick() {
    const nowMs = Date.now();
    for (const [, entry] of markers) {
      const [lat, lon] = displayLatLng(entry, nowMs);
      entry.marker.setLatLng([lat, lon]);
    }
    refreshConflictLine();
  }

  /** Render an aircraft_snapshot: {airport, timestamp, aircraft:[...]}. */
  function updateAircraft(snapshot, conflictPairCallsigns) {
    const list = Array.isArray(snapshot.aircraft) ? snapshot.aircraft : [];
    const conflictSet = new Set(conflictPairCallsigns || []);
    const seen = new Set();
    const nowMs = Date.now();

    if (snapshot.airport) {
      const first = list[0];
      setAirport(snapshot.airport, first ? [first.lat, first.lon] : null);
    }

    for (const ac of list) {
      if (typeof ac.lat !== "number" || typeof ac.lon !== "number") continue;
      const id = ac.icao24 || ac.callsign;
      if (!id) continue;
      seen.add(id);

      const isConflict = ac.callsign && conflictSet.has(ac.callsign);
      const existing = markers.get(id);
      // Re-anchor to the fresh snapshot position; the CSS transition absorbs
      // the small gap between the extrapolated point and the new truth.
      const anchor = {
        lat: ac.lat,
        lon: ac.lon,
        velocity_kt: ac.velocity_kt,
        heading: ac.heading,
      };

      if (existing) {
        existing.marker.setLatLng([ac.lat, ac.lon]);
        existing.marker.setIcon(rotatedIcon(ac.heading, isConflict));
        existing.marker.setTooltipContent(tooltip(ac));
        existing.callsign = ac.callsign;
        existing.anchor = anchor;
        existing.snapMs = nowMs;
      } else {
        const marker = L.marker([ac.lat, ac.lon], {
          icon: rotatedIcon(ac.heading, isConflict),
        }).addTo(map);
        marker.bindTooltip(tooltip(ac), {
          direction: "top",
          offset: [0, -8],
          className: "tg-ac-tooltip",
          opacity: 1,
        });
        markers.set(id, { marker, callsign: ac.callsign, anchor, snapMs: nowMs });
      }
    }

    // remove stale markers no longer in the snapshot
    for (const [id, entry] of markers) {
      if (!seen.has(id)) {
        map.removeLayer(entry.marker);
        markers.delete(id);
      }
    }

    refreshConflictLine();
  }

  /** Highlight a conflict pair: recolor markers + draw red dashed line.
   *  callsigns = [csA, csB] from closest_pair; null/empty clears lines. */
  function setConflict(callsigns) {
    const pair = Array.isArray(callsigns) ? callsigns : [];
    conflictPair = pair.length === 2 ? pair : [];
    const pairSet = new Set(pair);

    for (const [, entry] of markers) {
      const isC = entry.callsign && pairSet.has(entry.callsign);
      const el = entry.marker.getElement();
      if (el) {
        const tri = el.querySelector(".tg-ac");
        if (tri) tri.classList.toggle("is-conflict", !!isC);
      }
    }

    refreshConflictLine();
  }

  // Start the dead-reckoning loop. Markers without fresh snapshots simply hold
  // (no aircraft yet → empty loop body, cheap).
  const tickTimer = setInterval(tick, TICK_MS);

  return {
    map,
    setAirport,
    recenterTo,
    clearAircraft,
    updateAircraft,
    setConflict,
    stop() {
      clearInterval(tickTimer);
    },
  };
}
