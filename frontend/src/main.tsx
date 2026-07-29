import React from "react"
import ReactDOM from "react-dom/client"
import { HashRouter } from "react-router-dom"
import { Toaster } from "sonner"
import App from "./App"
import { LanguageProvider } from "./i18n/LanguageContext"
import "./index.css"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LanguageProvider>
      <HashRouter>
        <App />
        <Toaster position="top-center" richColors />
      </HashRouter>
    </LanguageProvider>
  </React.StrictMode>,
)
