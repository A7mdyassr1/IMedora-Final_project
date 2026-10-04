/// Friendly name for `roles.name`.
String roleLabel(String role) {
  switch (role) {
    case 'admin':
      return 'Administrator';
    case 'biomedical_engineer':
      return 'Biomedical Engineer';
    case 'technician':
      return 'Technician';
    case 'department_user':
      return 'Hospital staff';
    default:
      if (role.isEmpty) return role;
      final spaced = role.replaceAll('_', ' ');
      return spaced[0].toUpperCase() + spaced.substring(1);
  }
}
