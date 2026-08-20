export interface AuthUser {
  id: number
  username: string
}

export interface AuthSession {
  access_token: string
  user: AuthUser
}

export interface AuthCredentials {
  username: string
  password: string
}
