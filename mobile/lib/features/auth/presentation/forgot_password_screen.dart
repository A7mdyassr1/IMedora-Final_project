import 'package:flutter/material.dart';

/// UI only. Later: POST /auth/forgot-password.
class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailCtrl = TextEditingController();
  bool _sent = false;

  @override
  void dispose() {
    _emailCtrl.dispose();
    super.dispose();
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _sent = true);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Reset password')),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: _sent
                ? Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.mark_email_read_outlined,
                          size: 56, color: theme.colorScheme.primary),
                      const SizedBox(height: 16),
                      Text(
                        'If an account exists for that email, reset instructions have been sent. '
                        'You can also contact your hospital IT / biomedical department.',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.bodyMedium,
                      ),
                      const SizedBox(height: 24),
                      FilledButton(
                        onPressed: () => Navigator.of(context).maybePop(),
                        child: const Text('Back to sign in'),
                      ),
                    ],
                  )
                : Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text('Enter your email and we will send reset instructions.',
                            style: theme.textTheme.bodyMedium),
                        const SizedBox(height: 16),
                        TextFormField(
                          controller: _emailCtrl,
                          keyboardType: TextInputType.emailAddress,
                          decoration: const InputDecoration(
                            labelText: 'Email',
                            prefixIcon: Icon(Icons.email_outlined),
                          ),
                          validator: (v) =>
                              (v == null || !v.contains('@')) ? 'Enter a valid email' : null,
                        ),
                        const SizedBox(height: 24),
                        FilledButton(
                            onPressed: _submit, child: const Text('Send instructions')),
                      ],
                    ),
                  ),
          ),
        ),
      ),
    );
  }
}
