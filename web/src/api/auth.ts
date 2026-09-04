import { api } from './client'
import type { LoginResponse, User } from '../types/api'

export async function login(username: string, password: string) {
  const { data } = await api.post<LoginResponse>('/api/v1/auth/login', { username, password })
  return data
}

export async function currentUser() {
  const { data } = await api.get<User>('/api/v1/auth/me')
  return data
}
