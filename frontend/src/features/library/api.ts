import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  type Album,
  api,
  type Job,
  type LibraryPage,
  type RuleSet,
  unwrap,
  unwrapEmpty,
} from "@/lib/api/client";
import { keys, upsertJob } from "@/lib/api/keys";
import { useEventsStore } from "@/lib/events";

export const PAGE_SIZE = 120;

export type View = "all" | "duplicates" | "quarantine" | "album";
export type Sort = "added" | "taken" | "name" | "size" | "resolution" | "sharpness";

export interface LibraryQuery {
  view: View;
  albumId?: string;
  q?: string;
  similarTo?: string;
  rules: RuleSet;
  sort: Sort;
  order: "asc" | "desc";
}

function useFallback(ms: number): number | false {
  return useEventsStore((s) => s.status === "open") ? false : ms;
}

function queryParams(query: LibraryQuery) {
  return {
    view: query.view,
    album_id: query.view === "album" ? query.albumId : undefined,
    q: query.q?.trim() || undefined,
    similar_to: query.similarTo,
    rules: query.rules.rules?.length ? JSON.stringify(query.rules) : undefined,
    sort: query.sort,
    order: query.order,
  };
}

export function useLibraryPages(query: LibraryQuery) {
  const params = queryParams(query);
  const refetchInterval = useFallback(5_000);
  return useInfiniteQuery({
    queryKey: keys.libraryPage(params),
    initialPageParam: 0,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/library/assets", {
          params: { query: { ...params, offset: pageParam, limit: PAGE_SIZE } },
        }),
      ),
    getNextPageParam: (last: LibraryPage) =>
      last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined,
    placeholderData: keepPreviousData,
    refetchInterval,
    retry: false,
  });
}

export function useLibraryStatus() {
  const refetchInterval = useFallback(5_000);
  return useQuery({
    queryKey: keys.libraryStatus,
    queryFn: async () => unwrap(await api.GET("/api/library/status")),
    refetchInterval,
  });
}

export function useAlbums() {
  return useQuery({
    queryKey: keys.albums,
    queryFn: async () => unwrap(await api.GET("/api/library/albums")),
  });
}

export function useAssetAlbums(assetId: string | undefined) {
  return useQuery({
    queryKey: keys.assetAlbums(assetId ?? ""),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/library/assets/{asset_id}/albums", {
          params: { path: { asset_id: assetId ?? "" } },
        }),
      ),
    enabled: Boolean(assetId),
  });
}

export function useImportStatus() {
  const refetchInterval = useFallback(10_000);
  return useQuery({
    queryKey: keys.importStatus,
    queryFn: async () => unwrap(await api.GET("/api/library/import")),
    refetchInterval,
  });
}

/** Every Library change refreshes the lists, counts and albums. */
function useLibraryMutation<A>(fn: (arg: A) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.library });
      void client.invalidateQueries({ queryKey: keys.assets, exact: true });
    },
  });
}

export const useQuarantine = () =>
  useLibraryMutation(async ({ ids, reason }: { ids: string[]; reason?: string }) =>
    unwrap(await api.POST("/api/library/quarantine", { body: { asset_ids: ids, reason } })),
  );

export const useRestore = () =>
  useLibraryMutation(async (ids: string[]) =>
    unwrap(await api.POST("/api/library/restore", { body: { asset_ids: ids } })),
  );

export const useDeleteForever = () =>
  useLibraryMutation(async (ids: string[]) =>
    unwrap(await api.POST("/api/library/delete", { body: { asset_ids: ids } })),
  );

export const useResolveDuplicates = () =>
  useLibraryMutation(async (groups: string[] | null) =>
    unwrap(await api.POST("/api/library/duplicates/resolve", { body: { groups } })),
  );

export const useKeepAll = () =>
  useLibraryMutation(async (group: string) =>
    unwrap(
      await api.POST("/api/library/duplicates/{group_id}/keep-all", {
        params: { path: { group_id: group } },
      }),
    ),
  );

export const useEditTags = () =>
  useLibraryMutation(
    async ({ ids, add = [], remove = [] }: { ids: string[]; add?: string[]; remove?: string[] }) =>
      unwrap(await api.POST("/api/library/tags", { body: { asset_ids: ids, add, remove } })),
  );

export const useAlbumMembers = () =>
  useLibraryMutation(
    async ({ albumId, ids, action }: { albumId: string; ids: string[]; action: "add" | "remove" }) =>
      unwrap(
        await api.POST("/api/library/albums/{album_id}/assets", {
          params: { path: { album_id: albumId } },
          body: { asset_ids: ids, action },
        }),
      ),
  );

export function useSaveAlbum() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (album: { id?: string; name: string; kind: Album["kind"]; rules: RuleSet }) =>
      album.id
        ? unwrap(
            await api.PATCH("/api/library/albums/{album_id}", {
              params: { path: { album_id: album.id } },
              body: { name: album.name, rules: album.kind === "smart" ? album.rules : undefined },
            }),
          )
        : unwrap(
            await api.POST("/api/library/albums", {
              body: { name: album.name, kind: album.kind, rules: album.rules },
            }),
          ),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.library }),
  });
}

export const useDeleteAlbum = () =>
  useLibraryMutation(async (id: string) =>
    unwrapEmpty(await api.DELETE("/api/library/albums/{album_id}", { params: { path: { album_id: id } } })),
  );

export function useRemoveLocation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (ids: string[]) =>
      unwrap(await api.POST("/api/library/remove-location", { body: { asset_ids: ids } })),
    onSuccess: (job: Job) => {
      client.setQueryData<Job[]>(keys.jobs, (list) => upsertJob(list, job));
      client.setQueryData(keys.job(job.id), job);
    },
  });
}

export const useScanImport = () =>
  useLibraryMutation(async () => unwrapEmpty(await api.POST("/api/library/import/scan")));

export const useReindex = () =>
  useLibraryMutation(async () => unwrapEmpty(await api.POST("/api/library/reindex")));
