import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type User = {
  id: string
  email: string
}

type UserState = {
  user: User | null
  accessToken: string | null
  authLoading: boolean
  onboarded: boolean | null
  setUser: (user: User | null) => void
  setAccessToken: (token: string | null) => void
  setAuthLoading: (loading: boolean) => void
  setOnboarded: (onboarded: boolean) => void
  signOut: () => void
}

export const useUserStore = create<UserState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      authLoading: true,
      onboarded: null,
      setUser: (user) => set({ user }),
      setAccessToken: (accessToken) => set({ accessToken }),
      setAuthLoading: (authLoading) => set({ authLoading }),
      setOnboarded: (onboarded) => set({ onboarded }),
      signOut: () => set({ user: null, accessToken: null, authLoading: false, onboarded: null }),
    }),
    {
      name: 'llmwiki:user',
      partialize: (state) => ({ accessToken: state.accessToken }),
    },
  ),
)
