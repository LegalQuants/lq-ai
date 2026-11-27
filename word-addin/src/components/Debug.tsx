import { actions } from "@/actions";
import { skillsAtom, modelsAtom } from "@/store"
import { Button } from "@mantine/core";
import { useAtom } from "jotai"
import { JSONTree } from "react-json-tree"

export let Debug = () => {
  let [data] = useAtom(modelsAtom);


  return (
  <>
    <Button onClick={() => actions.copyToClipboard(JSON.stringify(data))}>Copy</Button>
    <JSONTree data={data} />
  </>)

}