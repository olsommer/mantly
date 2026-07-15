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

    // Attach JWT from localStorage on every request if present.
    // Embedded admin preview reuses the admin session token for preview and feedback.
    this.axiosInstance.interceptors.request.use((config) => {
      const token = localStorage.getItem('auth_token')
        || localStorage.getItem('admin_auth_token');
      if (token) {
        config.headers = config.headers ?? {};
        config.headers['Authorization'] = `Bearer ${token}`;
      }
      return config;
    });

    // Redirect to login on 401/403 — clear token and dispatch event for App.tsx
    this.axiosInstance.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        if (error.response?.status === 401 || error.response?.status === 403) {
          localStorage.removeItem('auth_token');
          localStorage.removeItem('auth_email');
          window.dispatchEvent(new Event('auth:session-changed'));
          window.dispatchEvent(new CustomEvent('frontend:unauthorized'));
        }
        return Promise.reject(error);
      }
    );
  }

  /**
   * Get the current base URL
   */
  getBaseUrl(): string {
    return this.axiosInstance.defaults.baseURL || '';
  }

  /**
   * Update base URL at runtime
   */
  setBaseUrl(url: string): void {
    this.axiosInstance.defaults.baseURL = url;
  }

  /**
   * Handle Axios errors consistently
   */
  private handleError(error: unknown): { error: string; status: number } {
    if (axios.isAxiosError(error)) {
      const axiosError = error as AxiosError<{ message?: string }>;
      
      if (axiosError.response) {
        // Server responded with error status
        return {
          error: axiosError.response.data?.message || axiosError.message,
          status: axiosError.response.status,
        };
      } else if (axiosError.request) {
        // Request was made but no response received
        return {
          error: 'No response from server',
          status: 0,
        };
      } else {
        // Something else happened
        return {
          error: axiosError.message,
          status: 0,
        };
      }
    }

    return {
      error: 'Unknown error occurred',
      status: 0,
    };
  }

  /**
   * GET request
   */
  async get<T>(endpoint: string, headers?: Record<string, string>): Promise<ApiResponse<T>> {
    try {
      const response = await this.axiosInstance.get<T>(endpoint, { headers });
      return {
        data: response.data,
        error: null,
        status: response.status,
      };
    } catch (error) {
      const { error: errorMsg, status } = this.handleError(error);
      return { data: null, error: errorMsg, status };
    }
  }

  /**
   * POST request
   */
  async post<T>(
    endpoint: string,
    body?: unknown,
    headers?: Record<string, string>
  ): Promise<ApiResponse<T>> {
    try {
      const response = await this.axiosInstance.post<T>(endpoint, body, { headers });
      return {
        data: response.data,
        error: null,
        status: response.status,
      };
    } catch (error) {
      const { error: errorMsg, status } = this.handleError(error);
      return { data: null, error: errorMsg, status };
    }
  }

  /**
   * PUT request
   */
  async put<T>(
    endpoint: string,
    body?: unknown,
    headers?: Record<string, string>
  ): Promise<ApiResponse<T>> {
    try {
      const response = await this.axiosInstance.put<T>(endpoint, body, { headers });
      return {
        data: response.data,
        error: null,
        status: response.status,
      };
    } catch (error) {
      const { error: errorMsg, status } = this.handleError(error);
      return { data: null, error: errorMsg, status };
    }
  }

  /**
   * DELETE request
   */
  async delete<T>(endpoint: string, headers?: Record<string, string>): Promise<ApiResponse<T>> {
    try {
      const response = await this.axiosInstance.delete<T>(endpoint, { headers });
      return {
        data: response.data,
        error: null,
        status: response.status,
      };
    } catch (error) {
      const { error: errorMsg, status } = this.handleError(error);
      return { data: null, error: errorMsg, status };
    }
  }

  /**
   * PATCH request
   */
  async patch<T>(
    endpoint: string,
    body?: unknown,
    headers?: Record<string, string>
  ): Promise<ApiResponse<T>> {
    try {
      const response = await this.axiosInstance.patch<T>(endpoint, body, { headers });
      return {
        data: response.data,
        error: null,
        status: response.status,
      };
    } catch (error) {
      const { error: errorMsg, status } = this.handleError(error);
      return { data: null, error: errorMsg, status };
    }
  }
}

// Singleton instance
const apiClient = new ApiClient();

export { apiClient, ApiClient };
export type { ApiResponse };
