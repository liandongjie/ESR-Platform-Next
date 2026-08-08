export interface ApiValidationDetail {
  field: string
  message: string
  type: string
}

export interface ApiErrorPayload {
  code: string
  message: string
  details?: ApiValidationDetail[]
}
