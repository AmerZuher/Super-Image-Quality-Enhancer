import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ApiKey, api, unwrap, unwrapEmpty } from "@/lib/api/client";
import { keys } from "@/lib/api/keys";

export function useAuthStatus() {
  return useQuery({
    queryKey: keys.auth,
    queryFn: async () => unwrap(await api.GET("/api/auth/status")),
    staleTime: 60_000,
    retry: 1,
  });
}

export function useSignIn() {
  return useMutation({
    mutationFn: async (key: string) => unwrap(await api.POST("/api/auth/session", { body: { key } })),
    // A fresh page load reconnects the live events and refetches everything with the new cookie.
    onSuccess: () => window.location.reload(),
  });
}

export function useSignOut() {
  return useMutation({
    mutationFn: async () => unwrapEmpty(await api.DELETE("/api/auth/session")),
    onSuccess: () => window.location.reload(),
  });
}

export function useApiKeys() {
  return useQuery({
    queryKey: keys.apiKeys,
    queryFn: async () => unwrap(await api.GET("/api/keys")),
  });
}

export function useCreateKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => unwrap(await api.POST("/api/keys", { body: { name } })),
    onSuccess: (created) => client.setQueryData<ApiKey[]>(keys.apiKeys, (list) => [created, ...(list ?? [])]),
  });
}

export function useRevokeKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrapEmpty(await api.DELETE("/api/keys/{key_id}", { params: { path: { key_id: id } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.apiKeys }),
  });
}
