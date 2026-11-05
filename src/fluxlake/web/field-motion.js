/* Motion begins at visibility. The default markup and CSS are fully visible. */
(() => {
  if (!("IntersectionObserver" in window) || !("MutationObserver" in window)) return;

  const preference = matchMedia("(prefers-reduced-motion: reduce)");
  const content = document.getElementById("content");
  const selector = "[data-reveal], #content > :is(.panel, .stats, .observatory-canvas, .replay-verdict)";
  let revealObserver;
  let contentObserver;

  function observeSections() {
    document.querySelectorAll(selector).forEach(section => {
      if (!section.classList.contains("field-revealed")) revealObserver.observe(section);
    });
  }

  function syncPreference() {
    revealObserver?.disconnect();
    contentObserver?.disconnect();
    if (preference.matches) return;

    revealObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        revealObserver.unobserve(entry.target);
        entry.target.classList.add("field-revealed");
      });
    }, { threshold: 0.07 });
    observeSections();

    contentObserver = new MutationObserver(observeSections);
    if (content) contentObserver.observe(content, { childList: true });
  }

  preference.addEventListener("change", syncPreference);
  syncPreference();
})();
