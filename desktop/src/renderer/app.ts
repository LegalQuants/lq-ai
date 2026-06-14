import { renderWizard } from './wizard'
import { renderPanel } from './panel'
import type { LqaiBridge } from '../preload'

declare global {
	interface Window {
		lqai: LqaiBridge
	}
}

const root = document.getElementById('root')!

async function main(): Promise<void> {
	const firstRun = await window.lqai.isFirstRun()
	if (firstRun) renderWizard(root, () => renderPanel(root))
	else renderPanel(root)
}

main()
