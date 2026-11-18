// Offline fallback page: reload the page the user asked for as soon as the network is back (CSP forbids inline JS).
// Listens for the browser's "online" event and also checks the server every few seconds, because "online" only
// means a network interface is up, and some browsers don't fire it reliably.
(function () {
  var done = false;
  function back() {
    if (done) return;
    done = true;
    var s = document.getElementById("status");
    if (s) s.textContent = "Back online. Reloading…";
    setTimeout(function () { location.reload(); }, 300);
  }
  function check() {
    fetch("/api/health", { cache: "no-store" }).then(function (r) { if (r.ok) back(); }).catch(function () {});
  }
  var retry = document.getElementById("retry");
  if (retry) retry.addEventListener("click", function (e) { e.preventDefault(); location.reload(); });
  window.addEventListener("online", check);
  setInterval(check, 4000);
})();
