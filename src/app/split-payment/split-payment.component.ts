import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

interface Payer {
  name: string;
  scb?: string;
  promptpay?: string;
}

interface Item {
  name: string;
  price: number;
  paidBy: string;
  splitWith: Record<string, boolean>;
}

@Component({
  selector: 'app-split-payment',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatButtonModule,
    MatIconModule
  ],
  templateUrl: './split-payment.component.html'
})
export class SplitPaymentComponent {
  payers: Payer[] = [{ name: 'หลง', scb: '', promptpay: '' }];
  items: Item[] = [
    {
      name: '',
      price: 0,
      paidBy: '',
      splitWith: { 'หลง': false }
    }
  ];

  // ✅ ตัวแปรสำหรับทดสอบสลิป
  testFrom = '';
  testTo = '';
  testAmount: number | null = null;
  slipResult: boolean | null = null;

  addPayer() {
    const newName = 'คนที่ ' + (this.payers.length + 1);
    this.payers.push({ name: newName, scb: '', promptpay: '' });
    this.items.forEach(item => {
      item.splitWith[newName] = false;
    });
  }

  removePayer(index: number) {
    const nameToRemove = this.payers[index].name;
    this.payers.splice(index, 1);
    this.items.forEach(item => {
      if (item.paidBy === nameToRemove) item.paidBy = '';
      delete item.splitWith[nameToRemove];
    });
  }

  addItem() {
    const splitWith: Record<string, boolean> = {};
    this.payers.forEach(p => splitWith[p.name] = false);
    this.items.push({
      name: '',
      price: 0,
      paidBy: '',
      splitWith
    });
  }

  removeItem(index: number) {
    this.items.splice(index, 1);
  }

  getAmountToPay(payerName: string): number {
    let total = 0;
    for (const item of this.items) {
      if (item.splitWith[payerName]) {
        const shareCount = Object.values(item.splitWith).filter(Boolean).length;
        if (shareCount > 0) total += item.price / shareCount;
      }
      if (item.paidBy === payerName) {
        total -= item.price;
      }
    }
    return total;
  }

  getNetBalances(): Record<string, number> {
    const result: Record<string, number> = {};
    this.payers.forEach(p => result[p.name] = 0);

    for (const item of this.items) {
      const splitNames = Object.entries(item.splitWith)
        .filter(([_, checked]) => checked)
        .map(([name]) => name);
      const share = item.price / splitNames.length;

      splitNames.forEach(name => result[name] += share);
      if (item.paidBy) result[item.paidBy] -= item.price;
    }

    Object.keys(result).forEach(name => {
      result[name] = parseFloat(result[name].toFixed(2));
    });

    return result;
  }

  getTransferInstructions(): { from: string; to: string; amount: number }[] {
    const net = this.getNetBalances();
    const payers = Object.keys(net);
    const debtors = payers.filter(p => net[p] > 0).sort((a, b) => net[b] - net[a]);
    const creditors = payers.filter(p => net[p] < 0).sort((a, b) => net[a] - net[b]);

    const transfers: { from: string; to: string; amount: number }[] = [];

    let i = 0, j = 0;
    while (i < debtors.length && j < creditors.length) {
      const from = debtors[i];
      const to = creditors[j];
      const amount = Math.min(net[from], -net[to]);

      if (amount > 0) {
        transfers.push({ from, to, amount: parseFloat(amount.toFixed(2)) });
        net[from] -= amount;
        net[to] += amount;
      }

      if (net[from] <= 0.01) i++;
      if (net[to] >= -0.01) j++;
    }

    return transfers;
  }

  getPayerByName(name: string): Payer | undefined {
    return this.payers.find(p => p.name === name);
  }

  shareLink() {
    const url = window.location.href;
    const balances = this.getNetBalances();

    const lines = ['Go-Dutch แชร์ค่าอาหาร 🍽', '', '📊 สรุปยอด'];

    for (const [name, amount] of Object.entries(balances)) {
      const sign = amount >= 0 ? '' : '-';
      lines.push(`${name}: ${sign}${Math.abs(amount).toFixed(2)} ฿`);
    }

    lines.push('', `📤 ${url}`);

    const text = lines.join('\n');

    if (navigator.share) {
      navigator.share({ title: 'Go-Dutch แชร์บิล', text, url })
        .catch(err => console.error('❌ แชร์ล้มเหลว', err));
    } else {
      navigator.clipboard.writeText(text);
      alert('คัดลอกข้อความเรียบร้อยแล้ว ✅');
    }
  }

  checkSlipValid(from: string, to: string, amount: number): boolean {
    const transfers = this.getTransferInstructions();
    return transfers.some(t =>
      t.from === from &&
      t.to === to &&
      Math.abs(t.amount - amount) < 0.01
    );
  }

  verifySlip() {
    if (this.testFrom && this.testTo && this.testAmount !== null) {
      this.slipResult = this.checkSlipValid(this.testFrom.trim(), this.testTo.trim(), this.testAmount);
    } else {
      alert('กรุณากรอกข้อมูลให้ครบ');
    }
  }


  trackByName(index: number, payer: any) {
    return payer.name;
  }
}