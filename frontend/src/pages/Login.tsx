import { useState } from "react"
import { api } from "@/api/client"
import { setToken } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Package, Lock, User } from "lucide-react"
import { toast } from "sonner"

export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username) { toast.warning("请输入用户名"); return }
    if (!password) { toast.warning("请输入密码"); return }
    setLoading(true)
    try {
      const res = await api.login(username, password)
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
    <div className="flex min-h-screen items-center justify-center bg-muted px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <Package className="h-12 w-12 text-primary" />
          <CardTitle className="text-xl">ZFundPilot</CardTitle>
          <p className="text-sm text-muted-foreground">个人基金分析与风险管理系统</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Label className="mb-1.5 block">用户名</Label>
              <div className="relative">
                <User className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <Input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="请输入用户名"
                  className="pl-9"
                  autoFocus
                />
              </div>
            </div>
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
