/*!
 * GEO Audit — snippet di tracking first-party
 * Uso: <script src="https://TUO-DOMINIO/static/js/geo-track.js" data-project="PROJECT_ID" async></script>
 * Eventi custom: window.geoTrack("nome_evento", {chiave: "valore"})
 */
(function () {
  var s = document.currentScript;
  if (!s) return;
  var pid = s.getAttribute("data-project");
  if (!pid) return;

  var endpoint = new URL(s.src, window.location.href).origin + "/t";
  var SID_KEY = "geo_sid";
  var sid;
  try {
    sid = sessionStorage.getItem(SID_KEY);
    if (!sid) {
      sid = Math.random().toString(36).slice(2) + Date.now().toString(36);
      sessionStorage.setItem(SID_KEY, sid);
    }
  } catch (e) {
    sid = Math.random().toString(36).slice(2);
  }

  function send(eventName, props) {
    var payload = JSON.stringify({
      pid: pid,
      event: eventName || "pageview",
      sid: sid,
      url: window.location.href,
      ref: document.referrer || "",
      props: (props && typeof props === "object") ? props : null,
    });
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon(endpoint, payload);
        return;
      }
    } catch (e) {}
    try {
      fetch(endpoint, { method: "POST", body: payload, keepalive: true, mode: "cors" }).catch(function () {});
    } catch (e) {}
  }

  send("pageview");
  window.geoTrack = send;
})();
