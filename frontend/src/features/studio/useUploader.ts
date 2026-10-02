import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import type { Asset } from "@/lib/api/client";
import { useCatalog } from "./api";
import { filterAccepted, startUploads } from "./uploads";

/** Upload files the server accepts; remembers the names of any it skipped. */
export function useUploader(onUploaded: (asset: Asset) => void) {
  const client = useQueryClient();
  const { data: catalog } = useCatalog();
  const [rejected, setRejected] = useState<string[]>([]);
  const extensions = useMemo(
    () => (catalog?.accepted_extensions ?? "").split(/\s+/).filter(Boolean),
    [catalog],
  );
  const upload = useCallback(
    (files: Iterable<File>) => {
      const [accepted, refused] = filterAccepted(files, extensions);
      setRejected(refused);
      startUploads(accepted, client, onUploaded);
    },
    [client, extensions, onUploaded],
  );
  return { upload, rejected, clearRejected: () => setRejected([]), accept: extensions.join(",") };
}
