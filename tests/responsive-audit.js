// Run through the documented CUA tab CDP capability against the local app.
// Open the desired form/dialog first. Call once per state/direction (<60s).
async function responsiveAudit(cdp, descending = false) {
  const widths = Array.from({length: 1493}, (_, i) => 220 + i * 5);
  if (descending) widths.reverse();
  const failures = [];
  for (const width of widths) {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width, height: width >= 1920 ? Math.round(width * 9 / 16) : 844,
      deviceScaleFactor: 1, mobile: false,
    });
    const result = await cdp.send('Runtime.evaluate', {returnByValue: true, expression: `(() => {
      const width = innerWidth;
      const elements = [...document.querySelectorAll('body *')].filter(el => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width && rect.height;
      });
      return {page: document.documentElement.scrollWidth > width + 1,
        outside: elements.filter(el => { const r = el.getBoundingClientRect();
          return r.left < -1 || r.right > width + 1;
        }).slice(0, 8).map(el => el.id || el.tagName)};
    })()`});
    const value = result.result.value;
    if (value.page || value.outside.length) failures.push({width, ...value});
  }
  await cdp.send('Emulation.clearDeviceMetricsOverride');
  return {checks: widths.length, failures};
}
