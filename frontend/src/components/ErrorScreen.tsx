// The "case opening/startup flow appropriate to the local-bound-case
// architecture" (mission Phase C, item 1): there is no in-UI case
// picker, because the architecture deliberately binds one server
// process to one case directory at startup (§11). This screen is what a
// user sees before that server is reachable, and tells them exactly how
// to start it -- never a generic "something went wrong".

export function ErrorScreen({ message, apiBaseUrl }: { message: string; apiBaseUrl: string }) {
  return (
    <div className="error-screen" data-testid="error-screen">
      <h1>Witnessgraph UI</h1>
      <p className="error-text">{message}</p>
      <p>This UI never opens a case directly -- it only talks to the local API server.</p>
      <p>To bind the server to a case and start it:</p>
      <pre>{`witnessgraph-api path/to/case-directory`}</pre>
      <p>
        Once it is running (it prints the URL it bound to), reload this page. The UI expects the
        API at <code>{apiBaseUrl}</code> -- override with the <code>VITE_API_BASE_URL</code>{' '}
        environment variable if it runs elsewhere.
      </p>
    </div>
  )
}
