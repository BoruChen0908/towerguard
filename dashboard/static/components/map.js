// map.js — Leaflet map: aircraft markers, conflict highlighting, range ring

const NM_TO_M = 1852; // nautical mile -> meters
const RANGE_NM = 50;

// Approximate airport centers (lat, lon) for known demo airports.
// Falls back to first aircraft / world view if unknown.
const AIRPORTS = {
  KMDW: [41.7868, -87.7522],
  KJFK: [40.6413, -73.7781],
  KEWR: [40.6895, -74.1745],
  KBOS: [42.3656, -71.0096],
  KATL: [33.6407, -84.4277],
  KLGA: [40.7769, -73.8740],
};

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

  const markers = new Map(); // icao24 -> { marker, callsign }
  let rangeRing = null;
  let conflictLines = [];
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

  /** Set / refresh the 50NM range ring at the airport center. */
  function setAirport(code, fallbackLatLon) {
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

    if (!centered) {
      map.setView(center, 9);
      centered = true;
    }
  }

  /** Render an aircraft_snapshot: {airport, timestamp, aircraft:[...]}. */
  function updateAircraft(snapshot, conflictPairCallsigns) {
    const list = Array.isArray(snapshot.aircraft) ? snapshot.aircraft : [];
    const conflictSet = new Set(conflictPairCallsigns || []);
    const seen = new Set();

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

      if (existing) {
        existing.marker.setLatLng([ac.lat, ac.lon]);
        existing.marker.setIcon(rotatedIcon(ac.heading, isConflict));
        existing.marker.setTooltipContent(tooltip(ac));
        existing.callsign = ac.callsign;
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
        markers.set(id, { marker, callsign: ac.callsign });
      }
    }

    // remove stale markers no longer in the snapshot
    for (const [id, entry] of markers) {
      if (!seen.has(id)) {
        map.removeLayer(entry.marker);
        markers.delete(id);
      }
    }
  }

  /** Highlight a conflict pair: recolor markers + draw red dashed line.
   *  callsigns = [csA, csB] from closest_pair; null/empty clears lines. */
  function setConflict(callsigns) {
    // clear previous lines
    for (const ln of conflictLines) map.removeLayer(ln);
    conflictLines = [];

    const pair = Array.isArray(callsigns) ? callsigns : [];
    const pairSet = new Set(pair);
    const positions = [];

    for (const [, entry] of markers) {
      const isC = entry.callsign && pairSet.has(entry.callsign);
      const el = entry.marker.getElement();
      if (el) {
        const tri = el.querySelector(".tg-ac");
        if (tri) tri.classList.toggle("is-conflict", !!isC);
      }
      if (isC) positions.push(entry.marker.getLatLng());
    }

    if (positions.length === 2) {
      const line = L.polyline(positions, {
        color: "#ff4d4d",
        weight: 2,
        opacity: 0.9,
        dashArray: "6 6",
        interactive: false,
      }).addTo(map);
      conflictLines.push(line);
    }
  }

  return { map, setAirport, updateAircraft, setConflict };
}
