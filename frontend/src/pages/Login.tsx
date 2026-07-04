import { useState } from "react"
import { api } from "@/api/client"
import { setToken } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Package, Lock } from "lucide-react"
import { toast } from "sonner"

export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!password) { toast.warning("请输入密码"); return }
    setLoading(true)
    try {
      const res = await api.login(password)
      if (res.token) setToken(res.token)
      toast.success("登录成功")
      onSuccess()
    } catch (e) {
      toast.error(`登录失败: ${e}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <Package className="h-12 w-12 text-blue-500" />
          <CardTitle className="text-xl">ZFundPilot</CardTitle>
          <p className="text-sm text-muted-foreground">个人基金分析与风险管理系统</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Label className="mb-1.5 block">密码</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="请输入访问密码"
                  className="pl-9"
                  autoFocus
                />
              </div>
            </div>
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? "登录中..." : "登录"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
