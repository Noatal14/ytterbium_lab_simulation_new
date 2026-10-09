export class ZeusApiError extends Error { constructor(public code: string, message: string) { super(message); } }
export class SubmissionApiError extends Error { constructor(public code: string, message: string) { super(message); } }
export class SmokeLifecycleApiError extends Error { constructor(public code: string, message: string) { super(message); } }
export class ScreeningSubmissionApiError extends Error { constructor(public code: string, message: string) { super(message); } }
export class ScreeningLifecycleApiError extends Error { constructor(public code: string, message: string) { super(message); } }
export class RefinementSubmissionApiError extends Error { constructor(public code: string, message: string) { super(message); } }
export class RefinementLifecycleApiError extends Error { constructor(public code: string, message: string) { super(message); } }
