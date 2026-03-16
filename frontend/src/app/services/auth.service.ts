import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly TOKEN_KEY = 'st_auth_token';
  private tokenSubject = new BehaviorSubject<string | null>(this.getStoredToken());

  get token$(): Observable<string | null> {
    return this.tokenSubject.asObservable();
  }

  get token(): string | null {
    return this.tokenSubject.value;
  }

  get isAuthenticated(): boolean {
    return !!this.token;
  }

  setToken(token: string): void {
    sessionStorage.setItem(this.TOKEN_KEY, token);
    this.tokenSubject.next(token);
  }

  clearToken(): void {
    sessionStorage.removeItem(this.TOKEN_KEY);
    this.tokenSubject.next(null);
  }

  private getStoredToken(): string | null {
    return sessionStorage.getItem(this.TOKEN_KEY);
  }
}
