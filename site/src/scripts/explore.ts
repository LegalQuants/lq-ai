import { GuideReader } from './guide-reader';
import { docsSearch } from './docs-search';
import { tourPlayback } from './tour-playback';
import { searchFromHash } from '../lib/explore-state.mjs';

const explore = document.querySelector<HTMLElement>('[data-lq-explore]');
if (explore) {
  // A search handed over from another page's composer (`#q=…`). Read it and
  // drop it from the address before the reader records this page as its root,
  // so a reload or Back does not run it again.
  const handedOver = searchFromHash(location.hash);
  if (handedOver) history.replaceState(history.state, '', location.pathname + location.search);
  const search = explore.querySelector<HTMLElement>('[data-lq-search]')!;
  const reader = new GuideReader(explore.querySelector<HTMLDialogElement>('[data-lq-reader]')!, search.dataset.base!);
  const pause = tourPlayback(explore);
  docsSearch(search, reader, pause, handedOver);
  explore.querySelector('[data-lq-reader]')!.addEventListener('lq-reader-open', pause);
}
