import { useState } from "react"
import { api } from "@/api/client"
import { setToken } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Package, Lock, User } from "lucide-react"
import { toast } from "sonner"
import { useLang } from "@/i18n/LanguageContext"

export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const { t } = useLang()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username) { toast.warning(t.login.usernameRequired); return }
    if (!password) { toast.warning(t.login.passwordRequired); return }
    setLoading(true)
    try {
      const res = await api.login(username, password)
      if (res.token) setToken(res.token)
      toast.success(t.login.loginSuccess)
      onSuccess()
    } catch (e) {
      toast.error(`${t.login.loginFailed}: ${e}`)
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
          <p className="text-sm text-muted-foreground">{t.home.tagline}</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Label className="mb-1.5 block">{t.login.usernamePlaceholder}</Label>
              <div className="relative">
                <User className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <Input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder={t.login.usernamePlaceholder}
                  className="pl-9"
                  autoFocus
                />
              </div>
            </div>
            <div>
              <Label className="mb-1.5 block">{t.login.passwordPlaceholder}</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t.login.passwordPlaceholder}
                  className="pl-9"
                />
              </div>
            </div>
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? t.login.loggingIn : t.login.submit}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
