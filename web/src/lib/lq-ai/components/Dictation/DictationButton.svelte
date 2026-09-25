<script lang="ts">
	/**
	 * Composer mic toggle — DE-015 (browser-side dictation, PRD §9).
	 *
	 * Single call site (ChatPanel.svelte's composer row), so this owns
	 * the mic button, the live level-meter waveform, and the tooltip
	 * disclosing that dictation runs in-browser together rather than
	 * splitting into several one-off files.
	 *
	 * The waveform reads from its own getUserMedia+AnalyserNode stream
	 * purely for the level bars — SpeechRecognition doesn't expose audio
	 * levels itself. Recognition and metering run in parallel and are
	 * torn down together on stop/unmount.
	 */
	import { onDestroy } from 'svelte';
	import LqButton from '$lib/lq-ai/components/shared/LqButton.svelte';
	import LqGroup from '$lib/lq-ai/components/shared/LqGroup.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { IconMicrophone, IconMicrophoneOff } from '@tabler/icons-svelte';
	import { isDictationSupported, startDictation, type DictationSession } from './speechRecognition';

	/** Called once per finalized utterance — parent appends to composerText. */
	export let onFinal: (transcript: string) => void = () => undefined;
	export let disabled = false;

	const supported = isDictationSupported();

	let recording = false;
	let session: DictationSession | null = null;

	const BAR_COUNT = 24;
	let levels: number[] = Array(BAR_COUNT).fill(0.05);
	let audioStream: MediaStream | null = null;
	let audioContext: AudioContext | null = null;
	let rafId: number | null = null;

	async function startMeter() {
		try {
			audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
		} catch {
			// Mic permission is already required by SpeechRecognition itself;
			// if this fails independently we just skip the waveform.
			return;
		}

		audioContext = new AudioContext();
		const source = audioContext.createMediaStreamSource(audioStream);
		const analyser = audioContext.createAnalyser();
		analyser.fftSize = 256;
		source.connect(analyser);

		const data = new Uint8Array(analyser.frequencyBinCount);

		const tick = () => {
			analyser.getByteTimeDomainData(data);
			let sumSquares = 0;
			for (let i = 0; i < data.length; i++) {
				const normalized = (data[i] - 128) / 128;
				sumSquares += normalized * normalized;
			}
			const rms = Math.sqrt(sumSquares / data.length);
			levels = [...levels.slice(1), Math.min(1, Math.max(0.05, rms * 6))];
			rafId = requestAnimationFrame(tick);
		};
		rafId = requestAnimationFrame(tick);
	}

	function stopMeter() {
		if (rafId !== null) cancelAnimationFrame(rafId);
		rafId = null;
		audioStream?.getTracks().forEach((track) => track.stop());
		audioStream = null;
		audioContext?.close();
		audioContext = null;
		levels = Array(BAR_COUNT).fill(0.05);
	}

	function stop() {
		session?.stop();
		session = null;
		stopMeter();
		recording = false;
	}

	function start() {
		recording = true;
		startMeter();
		session = startDictation(
			{
				onInterim: () => undefined,
				onFinal: (transcript) => {
					if (transcript.trim()) onFinal(transcript);
				},
				onError: () => {
					stop();
				},
				onEnd: () => {
					recording = false;
					stopMeter();
				}
			},
			navigator.language
		);
	}

	function toggle() {
		if (recording) {
			stop();
		} else {
			start();
		}
	}

	onDestroy(stop);
</script>

{#if supported}
	<LqGroup gap="xs" align="center">
		{#if recording}
			<LqGroup gap={0} align="center" data-testid="lq-ai-dictation-waveform">
				{#each levels as level}
					<div
						class="lq-dictation-bar"
						style:height="{Math.max(2, Math.round(level * 20))}px"
					></div>
				{/each}
			</LqGroup>
		{/if}
		<Tooltip
			content="Dictation runs locally in your browser (Chrome or Safari) — no audio is sent to any server. Accuracy varies by browser and language."
		>
			<LqButton
				size="sm"
				variant={recording ? 'filled' : 'outline'}
				tone={recording ? 'red' : 'sage'}
				aria-label={recording ? 'Stop dictation' : 'Start dictation'}
				title={recording ? 'Stop dictation' : 'Dictate'}
				{disabled}
				on:click={toggle}
				data-testid="lq-ai-dictation-btn"
			>
				{#if recording}
					<IconMicrophoneOff size={16} />
				{:else}
					<IconMicrophone size={16} />
				{/if}
			</LqButton>
		</Tooltip>
	</LqGroup>
{/if}

<style>
	.lq-dictation-bar {
		width: 1px;
		background: var(--lq-error, #b54848);
		border-radius: 1px;
		align-self: center;
	}
</style>
