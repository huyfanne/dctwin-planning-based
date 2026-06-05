import { Component, type ReactNode } from 'react';

interface Props { children: ReactNode }
interface State { error: Error | null }

/**
 * Error boundary for the WebGL scene. A throw inside the r3f tree (bad GPU state,
 * a failed asset, a NaN geometry) would otherwise blank the whole app; here it
 * degrades to a readable message overlaid on the viewport instead.
 */
export default class SceneBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    // surface it for debugging without taking down the page
    console.error('3D scene error:', error);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            position: 'absolute', inset: 0, display: 'flex',
            alignItems: 'center', justifyContent: 'center', padding: 24,
          }}
        >
          <div className="error-msg" style={{ maxWidth: 520, textAlign: 'center' }}>
            3D scene failed to render: {this.state.error.message}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
