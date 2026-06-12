// airport.js — header airport switcher.
// Loads GET /airports into the <select>, and on change POSTs /airport/{icao}.
// On a successful switch it recenters the map, clears the fleet, and drops the
// panels into the neutral "SWITCHING…" state. Normal rendering resumes once a
// module event arrives whose `airport` matches the new selection — the runner
// fires an immediate cycle (≤5s) after a switch, so this clears quickly.

/**
 * @param {object} cfg
 * @param {HTMLSelectElement} cfg.select  the header <select>
 * @param {(icao:string)=>void} cfg.onSwitch  fired after a confirmed POST
 */
export function createAirportSwitcher({ select, onSwitch }) {
  let current = null; // last confirmed selection (for revert on failure)

  function setOptions(airports, selected) {
    // build fresh options immutably, then swap in one shot
    const opts = (Array.isArray(airports) ? airports : []).map((a) => {
      const o = document.createElement("option");
      o.value = a.icao;
      o.textContent = a.icao + (a.name ? ` — ${a.name}` : "");
      if (a.icao === selected) o.selected = true;
      return o;
    });
    select.replaceChildren(...opts);
    current = selected || null;
  }

  async function load() {
    try {
      const res = await fetch("/airports");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      setOptions(body.airports, body.selected);
    } catch (err) {
      console.error("airport list load failed", err);
      // leave the placeholder ---- option; the switcher just stays inert
    }
  }

  async function handleChange() {
    const icao = select.value;
    if (!icao || icao === current) return;

    select.disabled = true;
    try {
      const res = await fetch(`/airport/${encodeURIComponent(icao)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`); // 404 = invalid icao
      const body = await res.json();
      current = body.airport || icao;
      onSwitch(current);
    } catch (err) {
      console.error("airport switch failed", err);
      // revert the select to the last good value — never leave it lying
      if (current) select.value = current;
    } finally {
      select.disabled = false;
    }
  }

  select.addEventListener("change", handleChange);
  load();

  return { load };
}
