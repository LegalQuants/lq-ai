import { GuideReader } from './guide-reader';
import { docsSearch } from './docs-search';
import { tourPlayback } from './tour-playback';

const explore = document.querySelector<HTMLElement>('[data-lq-explore]');
if (explore) {
  const search = explore.querySelector<HTMLElement>('[data-lq-search]')!;
  const reader = new GuideReader(explore.querySelector<HTMLDialogElement>('[data-lq-reader]')!, search.dataset.base!);
  const pause = tourPlayback(explore);
  docsSearch(search, reader, pause);
  explore.querySelector('[data-lq-reader]')!.addEventListener('lq-reader-open', pause);
}
