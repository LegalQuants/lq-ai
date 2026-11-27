import { useEffect } from "react";

export function useEffectAsync(
  effect: (isMounted: boolean) => Promise<void>,
  dependencies: any[] = []
): void {
  useEffect(() => {
    let isMounted = true;

    const executeEffect = async () => {
      try {
        await effect(isMounted);
      } catch (error) {
        console.error("Error in useEffectAsync:", error);
      }
    };

    executeEffect();

    return () => {
      isMounted = false;
    };
  }, dependencies);
}
