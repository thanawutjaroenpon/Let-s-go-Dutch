import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment'; 

// Interfaces for strongly typed data
export interface SlipResult {
  filename: string;
  valid: boolean;
  amount: number | null;
  promptpay: string | null;
}

export interface SlipHistory {
  filename: string;
  amount: number | null;
  promptpay: string | null;
  status: boolean;
  created_at: string;
}

export interface AppState {
  payers: any[];
  items: any[];
}

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private baseUrl = environment.apiBaseUrl; // ✅ Use environment-specific base URL

  constructor(private http: HttpClient) {}

  // Upload slip images
  uploadSlips(files: File[]): Observable<{ results: SlipResult[] }> {
    const formData = new FormData();
    files.forEach(file => {
      formData.append('files', file);
    });
    return this.http.post<{ results: SlipResult[] }>(
      `${this.baseUrl}/slip/upload`,
      formData
    );
  }

  // Get slip history
  getSlipHistory(): Observable<SlipHistory[]> {
    return this.http.get<SlipHistory[]>(`${this.baseUrl}/slip/history`);
  }

  // Save app state (payers & items)
  saveState(state: AppState): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(
      `${this.baseUrl}/state/save`,
      state
    );
  }

  // Load saved app state
  loadState(): Observable<AppState> {
    return this.http.get<AppState>(`${this.baseUrl}/state/load`);
  }
}
