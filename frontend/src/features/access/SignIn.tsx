import { KeyRound, LogIn } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Button } from "@/components/ui/Button";
import { CopyCommand } from "@/components/ui/CopyCommand";
import { Logo } from "@/components/ui/Logo";
import { errorMessage } from "@/lib/api/client";
import { useSignIn } from "./api";

/** Shown instead of the app when it asks for an API key (SIQE_API_AUTH=keys) and this browser has none. */
export function SignIn() {
  const [key, setKey] = useState("");
  const signIn = useSignIn();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (key.trim()) signIn.mutate(key.trim());
  };
  const problem = signIn.error ? errorMessage(signIn.error) : null;
  return (
    <main className="dot-grid grid min-h-full place-items-center p-4">
      <form
        onSubmit={submit}
        className="grid w-full max-w-[440px] gap-4 rounded-xl border border-line bg-panel p-5 shadow-float"
        aria-labelledby="signin-title"
      >
        <div className="flex items-center gap-3">
          <Logo className="size-8" />
          <div>
            <h1 id="signin-title" className="font-display text-[19px] font-medium">
              Sign in to SIQE Studio
            </h1>
            <p className="text-[12.5px] text-fg-2">This app asks for an API key.</p>
          </div>
        </div>
        <label className="grid gap-1 text-[12.5px] text-fg-2">
          API key
          <input
            type="password"
            autoComplete="current-password"
            className="h-9 rounded-md border border-line-2 bg-panel-2 px-2.5 font-mono text-[12.5px] text-fg outline-none focus:border-cyan"
            placeholder="siqe_…"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            // biome-ignore lint/a11y/noAutofocus: the only thing to do on this screen
            autoFocus
          />
        </label>
        {problem && (
          <p role="alert" className="text-[12.5px] text-err">
            {problem.message}
          </p>
        )}
        <Button
          variant="primary"
          type="submit"
          icon={<LogIn />}
          loading={signIn.isPending}
          disabled={!key.trim()}
        >
          Sign in
        </Button>
        <div className="grid gap-1.5 border-t border-line pt-3 text-[12px] text-fg-2">
          <span className="flex items-center gap-1.5">
            <KeyRound className="size-3.5" aria-hidden="true" />
            No key yet? Make one where SIQE Studio runs:
          </span>
          <CopyCommand command={'docker compose exec api siqe keys create "my browser"'} label="command" />
        </div>
      </form>
    </main>
  );
}
