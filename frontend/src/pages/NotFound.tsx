import { Link } from "react-router-dom"
import { useLang } from "@/i18n/LanguageContext"
import { FileQuestion } from "lucide-react"

export default function NotFound() {
  const { t } = useLang()
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <FileQuestion className="h-12 w-12 text-muted-foreground/40" />
      <h1 className="mt-6 text-2xl font-bold tracking-tight">{t.notFound.title}</h1>
      <p className="mt-2 text-sm text-muted-foreground max-w-xs">{t.notFound.description}</p>
      <Link
        to="/"
        className="mt-6 inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
      >
        {t.notFound.backHome}
      </Link>
    </div>
  )
}
