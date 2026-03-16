import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { AuthService } from './auth.service';
import { NotificationService } from './notification.service';
import { BackendStatusService } from './backend-status.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const notify = inject(NotificationService);
  const status = inject(BackendStatusService);

  let request = req;
  if (auth.token) {
    request = req.clone({
      setHeaders: { Authorization: `Bearer ${auth.token}` }
    });
  }

  return next(request).pipe(
    catchError((err: HttpErrorResponse) => {
      const message = err.error?.detail || err.message || 'An unexpected error occurred';

      if (err.status === 0) {
        status.setWaking();
        notify.warning('Backend is waking up or unreachable. Retrying demo-safe flows where possible.');
      } else if (err.status === 401) {
        notify.error('Authentication required. Please set your API token.');
      } else if (err.status === 503) {
        status.setWaking();
        notify.warning('Backend is starting or a subsystem is warming up. Please try again shortly.');
      } else if (err.status >= 400) {
        notify.error(message);
      }

      // Any successful-ish response means backend is reachable
      if (err.status > 0) {
        status.setOnline();
      }

      return throwError(() => err);
    })
  );
};
