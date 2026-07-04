import { useState } from "react"
import { getChannels, saveChannels, getDefaultChannels } from "@/lib/channels"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { toast } from "sonner"
import { ChevronUp, ChevronDown, Plus, Trash2, RotateCcw, Save } from "lucide-react"

export default function Settings() {
  const [channels, setChannels] = useState<string[]>(() => getChannels())
  const [newChannel, setNewChannel] = useState("")

  const moveUp = (i: number) => {
    if (i === 0) return
    const next = [...channels]
    ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
    setChannels(next)
  }

  const moveDown = (i: number) => {
    if (i === channels.length - 1) return
    const next = [...channels]
    ;[next[i + 1], next[i]] = [next[i], next[i + 1]]
    setChannels(next)
  }

  const remove = (i: number) => {
    setChannels(channels.filter((_, idx) => idx !== i))
  }

  const add = () => {
    const name = newChannel.trim()
    if (!name) return
    if (channels.includes(name)) {
      toast.warning("该渠道已存在")
      return
    }
    setChannels([...channels, name])
    setNewChannel("")
  }

  const handleSave = () => {
    saveChannels(channels)
    toast.success("渠道顺序已保存")
  }

  const handleReset = () => {
    const defaults = getDefaultChannels()
    setChannels(defaults)
    saveChannels(defaults)
    toast.success("已恢复默认渠道顺序")
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl md:text-2xl font-bold">设置</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">渠道顺序</CardTitle>
          <p className="text-sm text-muted-foreground">
            排在最前面的渠道会作为交易表单的默认选择。上下箭头调整顺序。
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          {channels.map((ch, i) => (
            <div key={ch} className="flex items-center gap-3 rounded-lg border p-2.5">
              <div className="flex flex-col">
                <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => moveUp(i)} disabled={i === 0}>
                  <ChevronUp className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => moveDown(i)} disabled={i === channels.length - 1}>
                  <ChevronDown className="h-4 w-4" />
                </Button>
              </div>
              <span className="flex-1 font-medium">{ch}</span>
              <span className="text-xs text-muted-foreground">
                第 {i + 1} 位{i === 0 ? "（默认）" : ""}
              </span>
              <Button variant="ghost" size="icon" onClick={() => remove(i)}>
                <Trash2 className="h-4 w-4 text-red-500" />
              </Button>
            </div>
          ))}

          <div className="flex gap-2 pt-2">
            <Input
              value={newChannel}
              onChange={(e) => setNewChannel(e.target.value)}
              placeholder="新增渠道名称"
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add() } }}
              className="max-w-[200px]"
            />
            <Button variant="outline" onClick={add}>
              <Plus className="mr-1 h-4 w-4" /> 添加
            </Button>
          </div>

          <div className="flex gap-2 pt-2">
            <Button onClick={handleSave}>
              <Save className="mr-1 h-4 w-4" /> 保存
            </Button>
            <Button variant="outline" onClick={handleReset}>
              <RotateCcw className="mr-1 h-4 w-4" /> 恢复默认
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
