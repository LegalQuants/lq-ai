/**
 * The composer's hint needs about 300px; on a phone the box has about 200.
 * Below 30rem the input shows its `data-short-placeholder` instead.
 */
export function fitPlaceholder(input: HTMLInputElement) {
  const full = input.placeholder;
  const short = input.dataset.shortPlaceholder;
  if (!short) return;
  const narrow = matchMedia('(max-width: 30rem)');
  const fit = () => { input.placeholder = narrow.matches ? short : full; };
  fit();
  narrow.addEventListener('change', fit);
}
