import { Component, Input, OnChanges } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-sparkline',
  standalone: true,
  imports: [CommonModule],
  template: `
    <svg [attr.viewBox]="'0 0 ' + width + ' ' + height" [attr.width]="width" [attr.height]="height"
         preserveAspectRatio="none" style="display:block">
      <polyline [attr.points]="points" fill="none" [attr.stroke]="color" stroke-width="1.5"/>
    </svg>
  `
})
export class SparklineComponent implements OnChanges {
  @Input() data: number[] = [];
  @Input() width = 80;
  @Input() height = 24;
  @Input() color = '#4caf50';

  points = '';

  ngOnChanges(): void {
    if (this.data.length < 2) {
      this.points = '';
      return;
    }
    const min = Math.min(...this.data);
    const max = Math.max(...this.data);
    const range = max - min || 1;
    const n = this.data.length;
    const xStep = this.width / (n - 1);
    this.points = this.data.map((v, i) => {
      const x = i * xStep;
      const y = this.height - ((v - min) / range) * (this.height - 2) - 1;
      return `${x},${y}`;
    }).join(' ');
  }
}
