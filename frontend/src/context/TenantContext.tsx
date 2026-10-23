import React, { createContext, useContext, useState, useEffect } from 'react';
import { Institution } from '../types/banking';

interface TenantContextType {
  activeInstitutionId: string;
  setActiveInstitutionId: (id: string) => void;
  institutions: Institution[];
  setInstitutions: (institutions: Institution[]) => void;
  currentInstitution?: Institution;
  refreshInstitutions?: () => Promise<void> | void;
}

const TenantContext = createContext<TenantContextType | undefined>(undefined);

export const TenantProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeInstitutionId, setActiveInstitutionId] = useState<string>(() => {
    return localStorage.getItem('sentinel_tenant_id') || '10000000-0000-0000-0000-000000000001';
  });

  const [institutions, setInstitutions] = useState<Institution[]>([]);

  useEffect(() => {
    localStorage.setItem('sentinel_tenant_id', activeInstitutionId);
  }, [activeInstitutionId]);

  const fetchInstitutions = () => {
    const endpoint =
      typeof window !== 'undefined' && window.location?.origin && window.location.origin.startsWith('http')
        ? `${window.location.origin}/api/v1/institutions`
        : 'http://localhost:8000/api/v1/institutions';

    return fetch(endpoint)
      .then((res) => {
        if (!res.ok) throw new Error('Failed to fetch institutions');
        return res.json();
      })
      .then((data) => {
        if (data.items && data.items.length > 0) {
          setInstitutions(data.items);
          if (!data.items.some((i: Institution) => i.id === activeInstitutionId)) {
            const firstActive = data.items.find((i: Institution) => i.status === 'ACTIVE') || data.items[0];
            setActiveInstitutionId(firstActive.id);
          }
        }
      })
      .catch((err) => {
        if (process.env.NODE_ENV !== 'test') {
          console.warn('Could not fetch institutions, using fallback list', err);
        }
        const fallback: Institution[] = [
          {
            id: '10000000-0000-0000-0000-000000000001',
            institution_code: 'APEX_BANK',
            name: 'Apex Commercial Bank',
            routing_identifier: 'APEXUS33',
            country_code: 'USA',
            status: 'ACTIVE',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
          {
            id: '10000000-0000-0000-0000-000000000002',
            institution_code: 'MERIDIAN_TRUST',
            name: 'Meridian Trust Company',
            routing_identifier: 'MRDNUS33',
            country_code: 'USA',
            status: 'ACTIVE',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ];
        setInstitutions(fallback);
      });
  };

  useEffect(() => {
    fetchInstitutions();
  }, []);

  const currentInstitution = institutions.find((i) => i.id === activeInstitutionId);

  return (
    <TenantContext.Provider
      value={{
        activeInstitutionId,
        setActiveInstitutionId,
        institutions,
        setInstitutions,
        currentInstitution,
        refreshInstitutions: fetchInstitutions,
      }}
    >
      {children}
    </TenantContext.Provider>
  );
};

export const useTenant = () => {
  const context = useContext(TenantContext);
  if (!context) {
    throw new Error('useTenant must be used within a TenantProvider');
  }
  return context;
};
