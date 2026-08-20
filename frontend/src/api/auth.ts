import { http } from '@/api/http'
import type { AuthCredentials, AuthSession, AuthUser } from '@/types/auth'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseAuthUser(value: unknown): AuthUser {
  if (
    !isRecord(value) ||
    typeof value.id !== 'number' ||
    !Number.isInteger(value.id) ||
    value.id <= 0 ||
    typeof value.username !== 'string' ||
    value.username.length === 0
  ) {
    throw new Error('认证响应格式不完整')
  }
  return value as unknown as AuthUser
}

export function parseAuthSession(value: unknown): AuthSession {
  if (
    !isRecord(value) ||
    typeof value.access_token !== 'string' ||
    value.access_token.length === 0
  ) {
    throw new Error('认证响应格式不完整')
  }
  return {
    access_token: value.access_token,
    user: parseAuthUser(value.user),
  }
}

export async function register(credentials: AuthCredentials): Promise<AuthSession> {
  const response = await http.post<unknown>('/auth/register', credentials)
  return parseAuthSession(response.data)
}

export async function login(credentials: AuthCredentials): Promise<AuthSession> {
  const response = await http.post<unknown>('/auth/login', credentials)
  return parseAuthSession(response.data)
}

export async function refreshSession(): Promise<AuthSession> {
  const response = await http.post<unknown>('/auth/refresh')
  return parseAuthSession(response.data)
}

export async function logout(): Promise<void> {
  await http.post('/auth/logout')
}

export async function getCurrentUser(): Promise<AuthUser> {
  const response = await http.get<unknown>('/auth/me')
  if (!isRecord(response.data)) throw new Error('认证响应格式不完整')
  return parseAuthUser(response.data.user)
}
