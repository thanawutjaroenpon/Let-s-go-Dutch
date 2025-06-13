import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SplitPaymentComponent } from './split-payment.component';

describe('SplitPaymentComponent', () => {
  let component: SplitPaymentComponent;
  let fixture: ComponentFixture<SplitPaymentComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SplitPaymentComponent]
    })
    .compileComponents();
    
    fixture = TestBed.createComponent(SplitPaymentComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
