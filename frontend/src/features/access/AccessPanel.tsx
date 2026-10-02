import { CheckCircle2, KeyRound, LogOut, Plus, ShieldCheck, ShieldOff, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { CopyCommand } from "@/components/ui/CopyCommand";
import { Panel } from "@/components/ui/Panel";
import { type ApiKeyCreated, errorMessage } from "@/lib/api/client";
import { relativeTime } from "@/lib/format";
import { useApiKeys, useAuthStatus, useCreateKey, useRevokeKey, useSignOut } from "./api";

const INPUT =
  "h-8 min-w-0 flex-1 rounded-md border border-line-2 bg-panel-2 px-2 text-[12.5px] text-fg outline-none focus:border-cyan";

function RevokeButton({ id, name }: { id: string; name: string }) {
  const revoke = useRevokeKey();
  const [armed, setArmed] = useState(false);
  return (
    <span className="grid justify-items-end gap-1">
      <Button
        size="sm"
        variant="danger"
        icon={<Trash2 />}
        loading={revoke.isPending}
        onClick={() => (armed ? revoke.mutate(id) : setArmed(true))}
        onBlur={() => setArmed(false)}
        aria-label={armed ? `Confirm revoking ${name}` : `Revoke ${name}`}
      >
        {armed ? "Revoke?" : "Revoke"}
      </Button>
      {revoke.error && (
        <span role="alert" className="max-w-[260px] text-right text-[11.5px] text-err">
          {errorMessage(revoke.error).message}
        </span>
      )}
    </span>
  );
}

/** Settings → Access: whether sign-in is on, and the API keys scripts and the CLI use. */
export function AccessPanel() {
  const { data: status } = useAuthStatus();
  const { data: list } = useApiKeys();
  const create = useCreateKey();
  const signOut = useSignOut();
  const [name, setName] = useState("");
  const [fresh, setFresh] = useState<ApiKeyCreated | null>(null);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(name.trim(), {
      onSuccess: (key) => {
        setFresh(key);
        setName("");
      },
    });
  };
  const keysOn = status?.mode === "keys";
  const active = (list ?? []).filter((k) => !k.revoked_at);
  return (
    <Panel
      title="Access"
      actions={
        keysOn ? (
          <Button size="sm" icon={<LogOut />} onClick={() => signOut.mutate()} loading={signOut.isPending}>
            Sign out
          </Button>
        ) : undefined
      }
    >
      <div className="grid gap-4">
        <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-fg-2">
          {keysOn ? (
            <Chip tone="ok" icon={<ShieldCheck />}>
              Sign-in on
            </Chip>
          ) : (
            <Chip tone="warn" icon={<ShieldOff />}>
              Sign-in off
            </Chip>
          )}
          <span>
            {keysOn
              ? `Every browser and script needs an API key. Signed in as “${status?.key_name ?? "?"}”.`
              : "Anyone who can reach this address can use it. Set SIQE_API_AUTH=keys in .env to ask for a key."}
          </span>
        </div>

        <section aria-labelledby="keys-title" className="grid gap-2">
          <h3 id="keys-title" className="text-[12.5px] font-semibold text-fg">
            API keys
          </h3>
          <p className="text-[12px] text-fg-2">
            For scripts and the <span className="font-mono">siqe</span> command. Send a key as{" "}
            <span className="font-mono">Authorization: Bearer …</span> or set{" "}
            <span className="font-mono">SIQE_API_KEY</span>.
          </p>
          <form onSubmit={submit} className="flex gap-2">
            <input
              className={INPUT}
              value={name}
              maxLength={80}
              onChange={(e) => setName(e.target.value)}
              placeholder="What it's for, e.g. laptop scripts"
              aria-label="New key name"
            />
            <Button
              type="submit"
              size="sm"
              icon={<Plus />}
              loading={create.isPending}
              disabled={!name.trim()}
            >
              Create key
            </Button>
          </form>
          {create.error && (
            <p role="alert" className="text-[12px] text-err">
              {errorMessage(create.error).message}
            </p>
          )}
          {fresh && (
            <div className="grid gap-1.5 rounded-lg border border-ok/40 bg-ok-soft p-3" role="status">
              <span className="flex items-center gap-1.5 text-[12.5px] font-medium text-ok">
                <CheckCircle2 className="size-4" aria-hidden="true" />
                Key “{fresh.name}” created. Copy it now: it won't be shown again.
              </span>
              <CopyCommand command={fresh.secret} label="API key" />
            </div>
          )}
          <ul className="grid divide-y divide-line rounded-lg border border-line">
            {(list ?? []).length === 0 && (
              <li className="px-3 py-2.5 text-[12.5px] text-muted">No keys yet.</li>
            )}
            {(list ?? []).map((key) => (
              <li key={key.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                <KeyRound className="size-4 text-muted" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12.5px] font-medium text-fg">{key.name}</span>
                  <span className="block font-mono text-[11px] text-muted">
                    {key.prefix}… · made {relativeTime(key.created_at)} ·{" "}
                    {key.last_used_at ? `used ${relativeTime(key.last_used_at)}` : "never used"}
                  </span>
                </span>
                {key.revoked_at ? (
                  <Chip icon={<ShieldOff />}>Revoked</Chip>
                ) : (
                  <RevokeButton id={key.id} name={key.name} />
                )}
              </li>
            ))}
          </ul>
          {keysOn && active.length === 1 && (
            <p className="text-[12px] text-fg-2">
              This is your only active key. Create another before revoking it, or you'll need the command line
              to get back in.
            </p>
          )}
        </section>
      </div>
    </Panel>
  );
}
