import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface SlipResult {
  filename: string;
  valid: boolean;
  verified: boolean;
  amount: number | null;
  promptpay: string | null;
  issuer_name?: string;
  receiver_name?: string;
}

export interface SlipHistory {
  filename: string;
  amount: number | null;
  promptpay: string | null;
  status: boolean;
  verified: boolean;
  issuer_name?: string;
  receiver_name?: string;
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
  private baseUrl = environment.apiBaseUrl;

  constructor(private http: HttpClient) {}

  uploadSlips(files: File[]): Observable<{ results: SlipResult[] }> {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    return this.http.post<{ results: SlipResult[] }>(`${this.baseUrl}/slip/upload`, formData);
  }

  getSlipHistory(): Observable<SlipHistory[]> {
    return this.http.get<SlipHistory[]>(`${this.baseUrl}/slip/history`);
  }

  saveState(state: AppState): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.baseUrl}/state/save`, state);
  }

  loadState(): Observable<AppState> {
    return this.http.get<AppState>(`${this.baseUrl}/state/load`);
  }
}