import axios from 'axios';
import type { AxiosInstance, AxiosError } from 'axios';
import { settings } from '../settings';

/**
 * API Response wrapper
 */
interface ApiResponse<T> {
  data: T | null;
  error: string | null;
  status: number;
}

/**
 * Base API Client using Axios
 * Automatically uses the correct endpoint based on settings
 */
class ApiClient {
  private axiosInstance: AxiosInstance;

  constructor() {
    this.axiosInstance = axios.create({
      baseURL: settings.apiBaseUrl,
      timeout: 300000, // 5 minutes
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Inject Authorization header for every request when auth is enabled
    this.axiosInstance.interceptors.request.use((config) => {
      if (settings.requireAuth) {
        const token = localStorage.getItem('admin_auth_token');
        if (token) {
          config.headers = config.headers ?? {};
          config.headers['Authorization'] = `Bearer ${token}`;
        }
      }
      return config;
    });

    // Redirect to login only when the session is invalid. 403 can be a valid
    // permission denial and must not destroy the current admin session.
    this.axiosInstance.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        if (settings.requireAuth && error.response?.status === 401) {
          localStorage.removeItem('admin_auth_token');
          // Trigger a page-level event so App.tsx can switch to the login view
          window.dispatchEvent(new CustomEvent('admin:unauthorized'));
        }
        return Promise.reject(error);
      }
    );
  }

  getBaseUrl(): string {
    return this.axiosInstance.defaults.baseURL || '';
  }

  setBaseUrl(url: string): void {
    this.axiosInstance.defaults.baseURL = url;
  }

  private handleError(error: unknown): { error: string; status: number } {
    if (axios.isAxiosError(error)) {
      const axiosError = error as AxiosError<{ message?: string; detail?: string | { message?: string } }>;
      if (axiosError.response) {
        const detail = axiosError.response.data?.detail;
        return {
          error: axiosError.response.data?.message
            || (typeof detail === 'string' ? detail : detail?.message)
            || axiosError.message,
          status: axiosError.response.status,
        };
      } else if (axiosError.request) {
        return { error: 'No response from server', status: 0 };
      } else {
        return { error: axiosError.message, status: 0 };
      }
    }
    return { error: 'Unknown error occurred', status: 0 };
  }

  async get<T>(endpoint: string, headers?: Record<string, string>): Promise<ApiResponse<T>> {
    try {
      const response = await this.axiosInstance.get<T>(endpoint, { headers });
      return { data: response.data, error: null, status: response.status };
    } catch (error) {
      const { error: errorMsg, status } = this.handleError(error);
      return { data: null, error: errorMsg, status };
    }
  }

  async post<T>(endpoint: string, body?: unknown, headers?: Record<string, string>): Promise<ApiResponse<T>> {
    try {
      const response = await this.axiosInstance.post<T>(endpoint, body, { headers });
      return { data: response.data, error: null, status: response.status };
    } catch (error) {
      const { error: errorMsg, status } = this.handleError(error);
      return { data: null, error: errorMsg, status };
    }
  }

  async put<T>(endpoint: string, body?: unknown, headers?: Record<string, string>): Promise<ApiResponse<T>> {
    try {
      const response = await this.axiosInstance.put<T>(endpoint, body, { headers });
      return { data: response.data, error: null, status: response.status };
    } catch (error) {
      const { error: errorMsg, status } = this.handleError(error);
      return { data: null, error: errorMsg, status };
    }
  }

  async patch<T>(endpoint: string, body?: unknown, headers?: Record<string, string>): Promise<ApiResponse<T>> {
    try {
      const response = await this.axiosInstance.patch<T>(endpoint, body, { headers });
      return { data: response.data, error: null, status: response.status };
    } catch (error) {
      const { error: errorMsg, status } = this.handleError(error);
      return { data: null, error: errorMsg, status };
    }
  }

  async delete<T>(endpoint: string, headers?: Record<string, string>): Promise<ApiResponse<T>> {
    try {
      const response = await this.axiosInstance.delete<T>(endpoint, { headers });
      return { data: response.data, error: null, status: response.status };
    } catch (error) {
      const { error: errorMsg, status } = this.handleError(error);
      return { data: null, error: errorMsg, status };
    }
  }
}

const apiClient = new ApiClient();

export { apiClient, ApiClient };
export type { ApiResponse };
